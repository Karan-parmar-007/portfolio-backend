#!/usr/bin/env python3
"""One-off migration from the legacy portfolio Postgres + Mongo GridFS into new_backend.

See docs/portfolio-rewrite/02-DATA-MODEL-AND-MIGRATION.md §6.

Usage (from new_backend/):

    python migrate_legacy_data.py --dry-run
    python migrate_legacy_data.py --verbose
    python migrate_legacy_data.py --skip-media
    python migrate_legacy_data.py --only access_levels --only projects
    python migrate_legacy_data.py --truncate
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import aioboto3
import uuid6
from bson import ObjectId
from bson.errors import InvalidId
from gridfs import AsyncGridFSBucket
from pymongo import AsyncMongoClient
from slugify import slugify
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from botocore.client import Config

from app.api.routes.education.model import Education
from app.api.routes.media.media_service import _safe_filename, _sniff_dimensions
from app.api.routes.media.model import MediaAsset
from app.api.routes.profile.model import ProfileInfo
from app.api.routes.project.model import AccessLevel, Project, ProjectSkill
from app.api.routes.skill.model import Skill, SkillCategory
from app.api.routes.social_media.model import SocialMediaLink
from app.api.routes.work_experience.model import WorkExperience
from app.config import db_settings, legacy_settings, media_settings
from app.core.constants import MEDIA_KIND_PREFIX, SOCIAL_PLATFORMS, MediaKind

logger = logging.getLogger("migrate_legacy_data")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIGRATION_ORDER: tuple[str, ...] = (
    "access_levels",
    "skill_categories",
    "skills",
    "profile_info",
    "education",
    "work_experiences",
    "social_media_links",
    "projects",
    "project_skills",
)

# Reverse of FK dependency for truncate (children first).
TRUNCATE_ORDER: tuple[str, ...] = (
    "project_skills",
    "projects",
    "social_media_links",
    "work_experiences",
    "education",
    "profile_info",
    "skills",
    "skill_categories",
    "access_levels",
    "media_assets",
)

PUBLIC_ACCESS_NAMES = frozenset({"public", "open", "everyone", "all"})
PRIVATE_ACCESS_NAMES = frozenset(
    {"private", "owner", "owner-only", "owner only", "internal", "hidden", "restricted"}
)
SHOW_IN_ABOUT_NAMES = frozenset(
    {
        "python",
        "javascript",
        "typescript",
        "react",
        "fastapi",
        "pytorch",
        "docker",
    }
)

GRIDFS_BUCKETS = {
    MediaKind.PROFILE_IMAGE: "profile_files",
    MediaKind.RESUME: "resume_files",
    MediaKind.SKILL_ICON: "skill_files",
    MediaKind.PROJECT_COVER: "project_files",
}

GRIDFS_FALLBACK_BUCKETS = (
    "profile_files",
    "resume_files",
    "project_files",
    "skill_files",
    "fs",
)

BUCKET_TO_KIND = {
    "profile_files": MediaKind.PROFILE_IMAGE,
    "resume_files": MediaKind.RESUME,
    "skill_files": MediaKind.SKILL_ICON,
    "project_files": MediaKind.PROJECT_COVER,
    "fs": MediaKind.PROJECT_COVER,
}

_GARAGE_SERVICE = "s3"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _async_pg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://") :]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://") :]
    return url


def _host_port_from_url(url: str) -> str:
    parsed = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    host = parsed.hostname or "?"
    port = parsed.port or 5432
    return f"{host}:{port}"


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _normalize_description(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parts = [line.strip() for line in value.splitlines() if line.strip()]
        return parts
    return [str(value)]


def _normalize_contributors(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return {}


def _infer_is_public(name: str | None) -> bool:
    """Legacy accesslevel names are free-form. Default public so the site stays visible.

    Only names that clearly mean private stay hidden. Labels like "cannot be live"
    describe deployability, not visibility.
    """
    label = (name or "").strip().lower()
    if label in PRIVATE_ACCESS_NAMES:
        return False
    if label in PUBLIC_ACCESS_NAMES:
        return True
    return True


def _normalize_platform(name: str) -> str:
    platform = (name or "").strip().lower()
    if platform == "x":
        return "twitter"
    return platform


def _score_label(score: Decimal | float | None) -> str | None:
    if score is None:
        return None
    return "CGPA" if float(score) <= 10 else "%"


def _guess_content_type(filename: str | None, metadata: dict | None, kind: MediaKind) -> str:
    meta = metadata or {}
    raw = (
        meta.get("content_type")
        or meta.get("contentType")
        or meta.get("Content-Type")
        or ""
    )
    content_type = str(raw).split(";")[0].strip().lower()
    if content_type == "image/jpg":
        content_type = "image/jpeg"
    if content_type:
        return content_type

    guessed, _ = mimetypes.guess_type(filename or "")
    if guessed:
        guessed = guessed.lower()
        if guessed == "image/jpg":
            guessed = "image/jpeg"
        return guessed

    return "application/pdf" if kind == MediaKind.RESUME else "image/png"


def _allowed_types(kind: MediaKind) -> set[str]:
    if kind == MediaKind.RESUME:
        return media_settings.allowed_document_types
    return media_settings.allowed_image_types


def _max_bytes(kind: MediaKind) -> int:
    if kind == MediaKind.RESUME:
        return media_settings.MEDIA_MAX_DOCUMENT_BYTES
    return media_settings.MEDIA_MAX_IMAGE_BYTES


def _unique_slug(base: str, used: set[str]) -> str:
    candidate = slugify(base) or "item"
    value = candidate
    n = 2
    while value in used:
        value = f"{candidate}-{n}"
        n += 1
    used.add(value)
    return value


# ---------------------------------------------------------------------------
# Stats / id map
# ---------------------------------------------------------------------------


@dataclass
class TableStats:
    read: int = 0
    inserted: int = 0
    skipped: int = 0
    media_uploaded: int = 0


@dataclass
class MigrationContext:
    dry_run: bool
    skip_media: bool
    verbose: bool
    id_map_path: Path
    id_map: dict[str, str] = field(default_factory=dict)
    stats: dict[str, TableStats] = field(default_factory=dict)
    uploaded_keys: list[str] = field(default_factory=list)
    # GridFS ObjectIds newly written into id_map during the current table txn.
    pending_id_map_keys: list[str] = field(default_factory=list)
    seeded_public_access_id: UUID | None = None

    def stats_for(self, table: str) -> TableStats:
        if table not in self.stats:
            self.stats[table] = TableStats()
        return self.stats[table]

    def begin_table(self) -> None:
        self.uploaded_keys = []
        self.pending_id_map_keys = []

    def revert_pending_id_map(self) -> None:
        for key in self.pending_id_map_keys:
            self.id_map.pop(key, None)
        self.pending_id_map_keys = []

    def load_id_map(self) -> None:
        if not self.id_map_path.exists():
            self.id_map = {}
            return
        try:
            data = json.loads(self.id_map_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("id map root must be an object")
            self.id_map = {str(k): str(v) for k, v in data.items()}
            logger.info("Loaded %d id-map entries from %s", len(self.id_map), self.id_map_path)
        except Exception as exc:
            raise SystemExit(f"Failed to read id map {self.id_map_path}: {exc}") from exc

    def save_id_map(self) -> None:
        if self.dry_run:
            return
        self.id_map_path.write_text(
            json.dumps(self.id_map, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        logger.info("Wrote id map (%d entries) to %s", len(self.id_map), self.id_map_path)


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


async def _connect_legacy_pg(url: str) -> AsyncEngine:
    async_url = _async_pg_url(url)
    host_port = _host_port_from_url(async_url)
    # Neon (and other cloud hosts) require TLS; the -pooler hostname also
    # cannot use prepared-statement caching (PgBouncer transaction mode).
    connect_args: dict[str, Any] = {}
    host = (urlparse(async_url.replace("postgresql+asyncpg://", "postgresql://", 1)).hostname or "").lower()
    if "neon.tech" in host or "ssl=require" in async_url or "sslmode=require" in async_url:
        connect_args["ssl"] = True
    if "pooler" in host or "neon.tech" in host:
        connect_args["statement_cache_size"] = 0
    # Source is read-only — never allow writes to the legacy database.
    connect_args["server_settings"] = {"default_transaction_read_only": "on"}
    engine = create_async_engine(async_url, echo=False, connect_args=connect_args)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        raise SystemExit(
            f"Cannot connect to legacy Postgres at {host_port}. "
            f"Is the legacy database running?\n  {exc}"
        ) from exc
    logger.info("Connected to legacy Postgres at %s", host_port)
    return engine


async def _connect_new_pg() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    host_port = f"{db_settings.POSTGRES_SERVER}:{db_settings.POSTGRES_PORT}"
    engine = create_async_engine(
        db_settings.POSTGRES_URL,
        echo=db_settings.POSTGRES_ECHO,
        connect_args={"server_settings": {"timezone": "UTC"}},
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        raise SystemExit(
            f"Cannot connect to new Postgres at {host_port}.\n  {exc}"
        ) from exc
    logger.info("Connected to new Postgres at %s", host_port)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    return engine, factory


async def _connect_mongo(uri: str, db_name: str) -> AsyncMongoClient:
    import certifi

    client: AsyncMongoClient = AsyncMongoClient(
        uri,
        serverSelectionTimeoutMS=15000,
        tlsCAFile=certifi.where(),
    )
    try:
        await client.admin.command("ping")
        # Touch the target DB so a bad name surfaces early.
        _ = client[db_name].name
    except Exception as exc:
        await client.close()
        raise SystemExit(
            f"Cannot connect to legacy MongoDB (uri host unreachable or auth failed).\n  {exc}"
        ) from exc
    logger.info("Connected to legacy MongoDB db=%s", db_name)
    return client


async def _connect_garage():
    session = aioboto3.Session()
    garage_config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
    )
    client_cm = session.client(
        _GARAGE_SERVICE,
        endpoint_url=db_settings.GARAGE_ENDPOINT_URL,
        aws_access_key_id=db_settings.GARAGE_ACCESS_KEY,
        aws_secret_access_key=db_settings.GARAGE_SECRET_KEY,
        region_name=db_settings.GARAGE_REGION_NAME,
        config=garage_config,
    )
    client = await client_cm.__aenter__()
    try:
        await client.head_bucket(Bucket=db_settings.GARAGE_BUCKET_NAME)
    except Exception as exc:
        await client_cm.__aexit__(None, None, None)
        raise SystemExit(
            f"Cannot reach Garage bucket '{db_settings.GARAGE_BUCKET_NAME}' "
            f"at {db_settings.GARAGE_ENDPOINT_URL}.\n  {exc}"
        ) from exc
    logger.info(
        "Connected to Garage bucket=%s endpoint=%s",
        db_settings.GARAGE_BUCKET_NAME,
        db_settings.GARAGE_ENDPOINT_URL,
    )
    return client, client_cm


# ---------------------------------------------------------------------------
# Media migration
# ---------------------------------------------------------------------------


async def migrate_gridfs_file(
    *,
    ctx: MigrationContext,
    session: AsyncSession,
    mongo: AsyncMongoClient,
    garage_client: Any,
    gridfs_id: str | None,
    kind: MediaKind,
) -> UUID | None:
    """Upload one GridFS object into Garage + media_assets. Returns media_asset id."""
    if ctx.skip_media or not gridfs_id:
        return None

    oid_key = str(gridfs_id).strip()
    if not oid_key:
        return None

    # Idempotent: id map hit
    if oid_key in ctx.id_map:
        mapped = UUID(ctx.id_map[oid_key])
        existing = (
            await session.execute(select(MediaAsset).where(MediaAsset.id == mapped))
        ).scalar_one_or_none()
        if existing is not None:
            logger.debug("Media id-map hit %s -> %s", oid_key, mapped)
            return mapped
        logger.warning(
            "Id map has %s -> %s but media_assets row missing; will re-upload",
            oid_key,
            mapped,
        )

    if ctx.dry_run:
        logger.info("[dry-run] would upload GridFS %s kind=%s", oid_key, kind.value)
        return None

    try:
        object_id = ObjectId(oid_key)
    except InvalidId:
        logger.warning("Invalid GridFS ObjectId %r for kind=%s — skipping", oid_key, kind.value)
        return None

    bucket_names = [GRIDFS_BUCKETS[kind]]
    for extra in GRIDFS_FALLBACK_BUCKETS:
        if extra not in bucket_names:
            bucket_names.append(extra)

    content = b""
    filename = None
    metadata: dict[str, Any] = {}
    used_bucket = bucket_names[0]
    last_exc: Exception | None = None
    for bucket_name in bucket_names:
        bucket = AsyncGridFSBucket(
            mongo[legacy_settings.LEGACY_MONGO_DB_NAME], bucket_name=bucket_name
        )
        try:
            stream = await bucket.open_download_stream(object_id)
            content = await stream.read()
            filename = stream.filename
            metadata = stream.metadata if isinstance(stream.metadata, dict) else {}
            if getattr(stream, "content_type", None):
                metadata = {**(metadata or {}), "content_type": stream.content_type}
            used_bucket = bucket_name
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            continue

    if last_exc is not None and not content:
        logger.warning(
            "Failed to read GridFS %s from buckets %s: %s — leaving FK null",
            oid_key,
            ",".join(bucket_names),
            last_exc,
        )
        return None

    if not content:
        logger.warning("Empty GridFS object %s — skipping", oid_key)
        return None

    content_type = _guess_content_type(filename, metadata, kind)
    allowed = _allowed_types(kind)
    if content_type not in allowed:
        logger.warning(
            "Content type %r not allowed for %s (GridFS %s) — skipping",
            content_type,
            kind.value,
            oid_key,
        )
        return None

    max_bytes = _max_bytes(kind)
    if len(content) > max_bytes:
        logger.warning(
            "GridFS %s exceeds max size %d for %s — skipping",
            oid_key,
            max_bytes,
            kind.value,
        )
        return None

    checksum = hashlib.sha256(content).hexdigest()

    # Idempotent: checksum + kind
    existing = (
        await session.execute(
            select(MediaAsset).where(
                MediaAsset.checksum_sha256 == checksum,
                MediaAsset.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Existing committed media — safe to keep in id_map even if this table rolls back.
        ctx.id_map[oid_key] = str(existing.id)
        logger.debug(
            "Media checksum hit GridFS %s -> media %s kind=%s",
            oid_key,
            existing.id,
            kind.value,
        )
        return existing.id

    width, height = (None, None)
    if kind != MediaKind.RESUME:
        width, height = _sniff_dimensions(content, content_type)

    media_id = uuid6.uuid7()
    safe_name = _safe_filename(filename)
    object_key = f"{MEDIA_KIND_PREFIX[kind]}/{media_id}/{safe_name}"

    await garage_client.put_object(
        Bucket=db_settings.GARAGE_BUCKET_NAME,
        Key=object_key,
        Body=content,
        ContentType=content_type,
    )
    ctx.uploaded_keys.append(object_key)

    asset = MediaAsset(
        id=media_id,
        object_key=object_key,
        filename=safe_name,
        content_type=content_type,
        size_bytes=len(content),
        kind=kind,
        checksum_sha256=checksum,
        width=width,
        height=height,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(asset)
    await session.flush()

    # Track for rollback: this media_assets row is in the open transaction.
    ctx.id_map[oid_key] = str(media_id)
    ctx.pending_id_map_keys.append(oid_key)
    logger.info(
        "Uploaded media %s kind=%s key=%s (from GridFS %s)",
        media_id,
        kind.value,
        object_key,
        oid_key,
    )
    return media_id


async def _cleanup_uploaded_keys(garage_client: Any, keys: list[str]) -> None:
    for key in keys:
        try:
            await garage_client.delete_object(
                Bucket=db_settings.GARAGE_BUCKET_NAME,
                Key=key,
            )
            logger.info("Deleted orphan Garage object %s", key)
        except Exception as exc:
            logger.error("Failed to delete orphan Garage object %s: %s", key, exc)


# ---------------------------------------------------------------------------
# Legacy reads
# ---------------------------------------------------------------------------


async def _fetch_all(legacy_engine: AsyncEngine, sql: str) -> list[dict[str, Any]]:
    async with legacy_engine.connect() as conn:
        result = await conn.execute(text(sql))
        return [dict(row) for row in result.mappings().all()]


# ---------------------------------------------------------------------------
# Per-table migrators
# ---------------------------------------------------------------------------


async def migrate_access_levels(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    **_: Any,
) -> None:
    rows = await _fetch_all(
        legacy_engine,
        "SELECT id, name, description FROM accesslevel ORDER BY name",
    )
    stats = ctx.stats_for("access_levels")
    stats.read = len(rows)

    if not rows:
        logger.warning("Legacy accesslevel is empty — seeding public/private")
        public_id = uuid6.uuid7()
        private_id = uuid6.uuid7()
        ctx.seeded_public_access_id = public_id
        seeds = [
            {
                "id": public_id,
                "name": "public",
                "description": "Publicly visible",
                "is_public": True,
            },
            {
                "id": private_id,
                "name": "private",
                "description": "Owner only",
                "is_public": False,
            },
        ]
        if ctx.dry_run:
            stats.inserted = len(seeds)
            return
        for seed in seeds:
            now = _utc_now()
            stmt = (
                pg_insert(AccessLevel)
                .values(**seed, created_at=now, updated_at=now)
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "name": seed["name"],
                        "description": seed["description"],
                        "is_public": seed["is_public"],
                        "updated_at": now,
                    },
                )
            )
            await session.execute(stmt)
            stats.inserted += 1
        return

    for row in rows:
        row_id = row["id"]
        is_public = _infer_is_public(row.get("name"))
        payload = {
            "id": row_id,
            "name": row["name"],
            "description": row.get("description"),
            "is_public": is_public,
        }
        if ctx.dry_run:
            existing = (
                await session.execute(select(AccessLevel.id).where(AccessLevel.id == row_id))
            ).scalar_one_or_none()
            if existing:
                stats.skipped += 1
            else:
                stats.inserted += 1
            continue

        existing = (
            await session.execute(select(AccessLevel.id).where(AccessLevel.id == row_id))
        ).scalar_one_or_none()
        now = _utc_now()
        stmt = (
            pg_insert(AccessLevel)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": payload["name"],
                    "description": payload["description"],
                    "is_public": payload["is_public"],
                    "updated_at": now,
                },
            )
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


async def migrate_skill_categories(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    **_: Any,
) -> None:
    rows = await _fetch_all(
        legacy_engine,
        "SELECT id, name FROM skillcategory ORDER BY name",
    )
    stats = ctx.stats_for("skill_categories")
    stats.read = len(rows)

    for sequence, row in enumerate(rows, start=1):
        row_id = row["id"]
        payload = {"id": row_id, "name": row["name"], "sequence": sequence}
        if ctx.dry_run:
            existing = (
                await session.execute(
                    select(SkillCategory.id).where(SkillCategory.id == row_id)
                )
            ).scalar_one_or_none()
            stats.skipped += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue

        existing = (
            await session.execute(select(SkillCategory.id).where(SkillCategory.id == row_id))
        ).scalar_one_or_none()
        now = _utc_now()
        stmt = (
            pg_insert(SkillCategory)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "name": payload["name"],
                    "sequence": payload["sequence"],
                    "updated_at": now,
                },
            )
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


async def migrate_skills(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    mongo: AsyncMongoClient | None,
    garage_client: Any,
    **_: Any,
) -> None:
    rows = await _fetch_all(
        legacy_engine,
        """
        SELECT id, name, category_id, image_id
        FROM skill
        ORDER BY category_id NULLS LAST, name
        """,
    )
    stats = ctx.stats_for("skills")
    stats.read = len(rows)

    # sequence = position within category, ordered by name
    seq_counters: dict[Any, int] = {}

    for row in rows:
        cat = row.get("category_id")
        seq_counters[cat] = seq_counters.get(cat, 0) + 1
        sequence = seq_counters[cat]
        row_id = row["id"]
        show_in_about = (row["name"] or "").strip().lower() in SHOW_IN_ABOUT_NAMES

        media_before = len(ctx.uploaded_keys)
        icon_media_id = None
        if mongo is not None and garage_client is not None:
            icon_media_id = await migrate_gridfs_file(
                ctx=ctx,
                session=session,
                mongo=mongo,
                garage_client=garage_client,
                gridfs_id=row.get("image_id"),
                kind=MediaKind.SKILL_ICON,
            )
        if len(ctx.uploaded_keys) > media_before:
            stats.media_uploaded += 1
        elif ctx.dry_run and row.get("image_id") and not ctx.skip_media:
            if str(row["image_id"]) not in ctx.id_map:
                stats.media_uploaded += 1

        payload = {
            "id": row_id,
            "name": row["name"],
            "category_id": row.get("category_id"),
            "sequence": sequence,
            "icon_media_id": icon_media_id,
            "show_in_about": show_in_about,
        }

        if ctx.dry_run:
            existing = (
                await session.execute(select(Skill.id).where(Skill.id == row_id))
            ).scalar_one_or_none()
            stats.skipped += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue

        existing = (
            await session.execute(select(Skill.id).where(Skill.id == row_id))
        ).scalar_one_or_none()
        now = _utc_now()
        update_fields = {
            "name": payload["name"],
            "category_id": payload["category_id"],
            "sequence": payload["sequence"],
            "show_in_about": payload["show_in_about"],
            "updated_at": now,
        }
        if not ctx.skip_media:
            update_fields["icon_media_id"] = payload["icon_media_id"]

        stmt = (
            pg_insert(Skill)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(index_elements=["id"], set_=update_fields)
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


async def migrate_profile_info(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    mongo: AsyncMongoClient | None,
    garage_client: Any,
    **_: Any,
) -> None:
    rows = await _fetch_all(
        legacy_engine,
        """
        SELECT id, name, about, headline, email, phone, location,
               resume_file_id, profile_image_id
        FROM profileinfo
        """,
    )
    stats = ctx.stats_for("profile_info")
    stats.read = len(rows)

    for row in rows:
        row_id = row["id"]

        media_before = len(ctx.uploaded_keys)
        profile_image_media_id = None
        resume_media_id = None
        if mongo is not None and garage_client is not None:
            profile_image_media_id = await migrate_gridfs_file(
                ctx=ctx,
                session=session,
                mongo=mongo,
                garage_client=garage_client,
                gridfs_id=row.get("profile_image_id"),
                kind=MediaKind.PROFILE_IMAGE,
            )
            resume_media_id = await migrate_gridfs_file(
                ctx=ctx,
                session=session,
                mongo=mongo,
                garage_client=garage_client,
                gridfs_id=row.get("resume_file_id"),
                kind=MediaKind.RESUME,
            )
        stats.media_uploaded += max(0, len(ctx.uploaded_keys) - media_before)

        if ctx.dry_run and not ctx.skip_media:
            for gid in (row.get("profile_image_id"), row.get("resume_file_id")):
                if gid and str(gid) not in ctx.id_map:
                    stats.media_uploaded += 1

        payload = {
            "id": row_id,
            "name": row["name"],
            "headline": row.get("headline"),
            "hero_greeting": "Hi, my name is",
            "about": row.get("about"),
            "email": row["email"],
            "phone": row.get("phone"),
            "location": row.get("location"),
            "available_for_work": True,
            "resume_media_id": resume_media_id,
            "profile_image_media_id": profile_image_media_id,
        }

        if ctx.dry_run:
            existing = (
                await session.execute(select(ProfileInfo.id).where(ProfileInfo.id == row_id))
            ).scalar_one_or_none()
            stats.skipped += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue

        existing = (
            await session.execute(select(ProfileInfo.id).where(ProfileInfo.id == row_id))
        ).scalar_one_or_none()
        now = _utc_now()
        update_fields = {
            "name": payload["name"],
            "headline": payload["headline"],
            "hero_greeting": payload["hero_greeting"],
            "about": payload["about"],
            "email": payload["email"],
            "phone": payload["phone"],
            "location": payload["location"],
            "available_for_work": payload["available_for_work"],
            "updated_at": now,
        }
        if not ctx.skip_media:
            update_fields["resume_media_id"] = payload["resume_media_id"]
            update_fields["profile_image_media_id"] = payload["profile_image_media_id"]

        stmt = (
            pg_insert(ProfileInfo)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(index_elements=["id"], set_=update_fields)
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


async def migrate_education(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    **_: Any,
) -> None:
    # Legacy column is quoted "Score" (capital S).
    rows = await _fetch_all(
        legacy_engine,
        """
        SELECT id, sequence, school, degree, start_year, end_year,
               "Score" AS score, description
        FROM education
        ORDER BY sequence, start_year
        """,
    )
    stats = ctx.stats_for("education")
    stats.read = len(rows)

    for row in rows:
        row_id = row["id"]
        score = row.get("score")
        score_dec = Decimal(str(score)) if score is not None else None
        payload = {
            "id": row_id,
            "sequence": row["sequence"],
            "school": row["school"],
            "degree": row["degree"],
            "field_of_study": None,
            "start_year": row["start_year"],
            "end_year": row.get("end_year"),
            "score": score_dec,
            "score_label": _score_label(score_dec),
            "description": row.get("description"),
        }

        if ctx.dry_run:
            existing = (
                await session.execute(select(Education.id).where(Education.id == row_id))
            ).scalar_one_or_none()
            stats.skipped += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue

        existing = (
            await session.execute(select(Education.id).where(Education.id == row_id))
        ).scalar_one_or_none()
        now = _utc_now()
        stmt = (
            pg_insert(Education)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "sequence": payload["sequence"],
                    "school": payload["school"],
                    "degree": payload["degree"],
                    "field_of_study": payload["field_of_study"],
                    "start_year": payload["start_year"],
                    "end_year": payload["end_year"],
                    "score": payload["score"],
                    "score_label": payload["score_label"],
                    "description": payload["description"],
                    "updated_at": now,
                },
            )
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


async def migrate_work_experiences(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    **_: Any,
) -> None:
    rows = await _fetch_all(
        legacy_engine,
        """
        SELECT id, sequence, company, position, description, start_date, end_date
        FROM workexperience
        ORDER BY sequence, start_date
        """,
    )
    stats = ctx.stats_for("work_experiences")
    stats.read = len(rows)

    for row in rows:
        row_id = row["id"]
        payload = {
            "id": row_id,
            "sequence": row["sequence"],
            "company": row["company"],
            "company_url": None,
            "position": row["position"],
            "location": None,
            "employment_type": None,
            "description": _normalize_description(row.get("description")),
            "start_date": _as_date(row["start_date"]),
            "end_date": _as_date(row.get("end_date")),
        }

        if ctx.dry_run:
            existing = (
                await session.execute(
                    select(WorkExperience.id).where(WorkExperience.id == row_id)
                )
            ).scalar_one_or_none()
            stats.skipped += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue

        existing = (
            await session.execute(
                select(WorkExperience.id).where(WorkExperience.id == row_id)
            )
        ).scalar_one_or_none()
        now = _utc_now()
        stmt = (
            pg_insert(WorkExperience)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "sequence": payload["sequence"],
                    "company": payload["company"],
                    "company_url": payload["company_url"],
                    "position": payload["position"],
                    "location": payload["location"],
                    "employment_type": payload["employment_type"],
                    "description": payload["description"],
                    "start_date": payload["start_date"],
                    "end_date": payload["end_date"],
                    "updated_at": now,
                },
            )
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


async def migrate_social_media_links(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    **_: Any,
) -> None:
    rows = await _fetch_all(
        legacy_engine,
        """
        SELECT id, name, link, created_at
        FROM socialmedia
        ORDER BY created_at NULLS LAST, name
        """,
    )
    stats = ctx.stats_for("social_media_links")
    stats.read = len(rows)

    for sequence, row in enumerate(rows, start=1):
        row_id = row["id"]
        label = row["name"]
        platform = _normalize_platform(label)
        if platform not in SOCIAL_PLATFORMS:
            logger.warning(
                "Unknown social platform %r (id=%s) — importing anyway; fix in admin",
                label,
                row_id,
            )
        payload = {
            "id": row_id,
            "platform": platform,
            "label": label,
            "url": row["link"],
            "sequence": sequence,
            "show_in_rail": True,
        }

        if ctx.dry_run:
            existing = (
                await session.execute(
                    select(SocialMediaLink.id).where(SocialMediaLink.id == row_id)
                )
            ).scalar_one_or_none()
            stats.skipped += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue

        existing = (
            await session.execute(
                select(SocialMediaLink.id).where(SocialMediaLink.id == row_id)
            )
        ).scalar_one_or_none()
        now = _utc_now()
        stmt = (
            pg_insert(SocialMediaLink)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "platform": payload["platform"],
                    "label": payload["label"],
                    "url": payload["url"],
                    "sequence": payload["sequence"],
                    "show_in_rail": payload["show_in_rail"],
                    "updated_at": now,
                },
            )
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


async def migrate_projects(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    mongo: AsyncMongoClient | None,
    garage_client: Any,
    **_: Any,
) -> None:
    rows = await _fetch_all(
        legacy_engine,
        """
        SELECT id, created_at, name, short_description, long_description,
               access_level_id, github_link_backend, github_link_frontend,
               ngrok_url, is_interesting_project, is_live,
               docker_image_link_backend, docker_image_link_frontend,
               contributors, project_image_id
        FROM projects
        ORDER BY created_at ASC NULLS LAST, name
        """,
    )
    stats = ctx.stats_for("projects")
    stats.read = len(rows)

    # Existing slugs in new DB (other rows) + in-batch uniqueness.
    existing_slugs = set(
        (await session.execute(select(Project.slug))).scalars().all()
    )
    # When upserting, allow a project to keep/reuse its own slug — track id->slug.
    existing_rows = (
        await session.execute(select(Project.id, Project.slug))
    ).all()
    id_to_slug = {r.id: r.slug for r in existing_rows}

    used_slugs: set[str] = set(existing_slugs)

    for sequence, row in enumerate(rows, start=1):
        row_id = row["id"]

        # Slug: preserve existing slug on re-run if still unique for this id.
        if row_id in id_to_slug:
            slug = id_to_slug[row_id]
            used_slugs.add(slug)
        else:
            # Free the reserved set for collision checks among new rows only —
            # exclude this id's old slug (none) and generate uniquely.
            slug = _unique_slug(row["name"], used_slugs)

        access_level_id = row.get("access_level_id")
        if access_level_id is None and ctx.seeded_public_access_id is not None:
            access_level_id = ctx.seeded_public_access_id
        elif access_level_id is None:
            # Fall back to any public access level already in the new DB.
            public_id = (
                await session.execute(
                    select(AccessLevel.id)
                    .where(AccessLevel.is_public.is_(True))
                    .order_by(AccessLevel.name)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if public_id is None:
                raise RuntimeError(
                    f"Project {row_id} has no access_level_id and no public "
                    "access_levels row exists to attach to"
                )
            access_level_id = public_id
            logger.warning(
                "Project %s missing access_level_id — attaching to public %s",
                row_id,
                public_id,
            )

        media_before = len(ctx.uploaded_keys)
        cover_image_media_id = None
        if mongo is not None and garage_client is not None:
            cover_image_media_id = await migrate_gridfs_file(
                ctx=ctx,
                session=session,
                mongo=mongo,
                garage_client=garage_client,
                gridfs_id=row.get("project_image_id"),
                kind=MediaKind.PROJECT_COVER,
            )
        stats.media_uploaded += max(0, len(ctx.uploaded_keys) - media_before)

        if ctx.dry_run and not ctx.skip_media:
            gid = row.get("project_image_id")
            if gid and str(gid) not in ctx.id_map:
                stats.media_uploaded += 1

        payload = {
            "id": row_id,
            "name": row["name"],
            "slug": slug,
            "short_description": row["short_description"],
            "long_description": row["long_description"],
            "access_level_id": access_level_id,
            "sequence": sequence,
            "is_featured": bool(row.get("is_interesting_project") or False),
            "is_live": bool(row.get("is_live") or False),
            "live_url": row.get("ngrok_url"),
            "github_link_backend": row.get("github_link_backend"),
            "github_link_frontend": row.get("github_link_frontend"),
            "docker_image_link_backend": row.get("docker_image_link_backend"),
            "docker_image_link_frontend": row.get("docker_image_link_frontend"),
            "contributors": _normalize_contributors(row.get("contributors")),
            "cover_image_media_id": cover_image_media_id,
        }

        if ctx.dry_run:
            existing = (
                await session.execute(select(Project.id).where(Project.id == row_id))
            ).scalar_one_or_none()
            stats.skipped += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue

        existing = (
            await session.execute(select(Project.id).where(Project.id == row_id))
        ).scalar_one_or_none()
        now = _utc_now()
        update_fields = {
            "name": payload["name"],
            "slug": payload["slug"],
            "short_description": payload["short_description"],
            "long_description": payload["long_description"],
            "access_level_id": payload["access_level_id"],
            "sequence": payload["sequence"],
            "is_featured": payload["is_featured"],
            "is_live": payload["is_live"],
            "live_url": payload["live_url"],
            "github_link_backend": payload["github_link_backend"],
            "github_link_frontend": payload["github_link_frontend"],
            "docker_image_link_backend": payload["docker_image_link_backend"],
            "docker_image_link_frontend": payload["docker_image_link_frontend"],
            "contributors": payload["contributors"],
            "updated_at": now,
        }
        if not ctx.skip_media:
            update_fields["cover_image_media_id"] = payload["cover_image_media_id"]

        stmt = (
            pg_insert(Project)
            .values(**payload, created_at=now, updated_at=now)
            .on_conflict_do_update(index_elements=["id"], set_=update_fields)
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


async def migrate_project_skills(
    ctx: MigrationContext,
    legacy_engine: AsyncEngine,
    session: AsyncSession,
    **_: Any,
) -> None:
    rows = await _fetch_all(
        legacy_engine,
        "SELECT project_id, skill_id FROM project_skill",
    )
    stats = ctx.stats_for("project_skills")
    stats.read = len(rows)

    for row in rows:
        project_id = row["project_id"]
        skill_id = row["skill_id"]

        if ctx.dry_run:
            existing = (
                await session.execute(
                    select(ProjectSkill).where(
                        ProjectSkill.project_id == project_id,
                        ProjectSkill.skill_id == skill_id,
                    )
                )
            ).scalar_one_or_none()
            stats.skipped += 1 if existing else 0
            stats.inserted += 0 if existing else 1
            continue

        existing = (
            await session.execute(
                select(ProjectSkill).where(
                    ProjectSkill.project_id == project_id,
                    ProjectSkill.skill_id == skill_id,
                )
            )
        ).scalar_one_or_none()
        stmt = (
            pg_insert(ProjectSkill)
            .values(project_id=project_id, skill_id=skill_id)
            .on_conflict_do_nothing(index_elements=["project_id", "skill_id"])
        )
        await session.execute(stmt)
        if existing:
            stats.skipped += 1
        else:
            stats.inserted += 1


MIGATORS = {
    "access_levels": migrate_access_levels,
    "skill_categories": migrate_skill_categories,
    "skills": migrate_skills,
    "profile_info": migrate_profile_info,
    "education": migrate_education,
    "work_experiences": migrate_work_experiences,
    "social_media_links": migrate_social_media_links,
    "projects": migrate_projects,
    "project_skills": migrate_project_skills,
}


# ---------------------------------------------------------------------------
# Truncate
# ---------------------------------------------------------------------------


async def truncate_tables(session: AsyncSession, garage_client: Any) -> None:
    logger.warning("Truncating new-database tables for a clean re-import")

    # Collect media keys so we can clean Garage after deleting rows.
    assets = (await session.execute(select(MediaAsset))).scalars().all()
    keys = [a.object_key for a in assets]

    for table in TRUNCATE_ORDER:
        await session.execute(text(f"DELETE FROM {table}"))
        logger.info("Deleted all rows from %s", table)

    await session.commit()

    for key in keys:
        try:
            await garage_client.delete_object(
                Bucket=db_settings.GARAGE_BUCKET_NAME,
                Key=key,
            )
        except Exception as exc:
            logger.warning("Failed to delete Garage object %s during truncate: %s", key, exc)

    logger.info("Truncate complete (%d Garage objects removed)", len(keys))


async def copy_all_gridfs_to_garage(
    ctx: MigrationContext,
    session: AsyncSession,
    mongo: AsyncMongoClient,
    garage_client: Any,
) -> None:
    """Copy every readable GridFS file into Garage. Source Mongo is read-only."""
    db = mongo[legacy_settings.LEGACY_MONGO_DB_NAME]
    copied = 0
    skipped = 0
    for bucket_name, kind in BUCKET_TO_KIND.items():
        files_col = f"{bucket_name}.files"
        names = await db.list_collection_names()
        if files_col not in names:
            continue
        async for doc in db[files_col].find({}, {"_id": 1}):
            media_id = await migrate_gridfs_file(
                ctx=ctx,
                session=session,
                mongo=mongo,
                garage_client=garage_client,
                gridfs_id=str(doc["_id"]),
                kind=kind,
            )
            if media_id is None:
                skipped += 1
            else:
                copied += 1
    logger.info("Copied GridFS files into Garage: ok=%d skipped=%d", copied, skipped)
    ctx.save_id_map()


async def attach_latest_profile_media(session: AsyncSession) -> None:
    """If profile image/resume FKs are empty, attach the newest matching Garage assets."""
    profile = (await session.execute(select(ProfileInfo))).scalars().first()
    if profile is None:
        return

    async def latest(kind: MediaKind) -> UUID | None:
        row = (
            await session.execute(
                select(MediaAsset.id)
                .where(MediaAsset.kind == kind)
                .order_by(MediaAsset.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row

    changed = False
    if profile.profile_image_media_id is None:
        image_id = await latest(MediaKind.PROFILE_IMAGE)
        if image_id is not None:
            profile.profile_image_media_id = image_id
            changed = True
    if profile.resume_media_id is None:
        resume_id = await latest(MediaKind.RESUME)
        if resume_id is not None:
            profile.resume_media_id = resume_id
            changed = True
    if changed:
        session.add(profile)
        logger.info("Attached latest profile image/resume from Garage media_assets")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def print_summary(ctx: MigrationContext, tables: list[str]) -> None:
    headers = ("table", "read", "inserted", "skipped", "media uploaded")
    rows: list[tuple[str, str, str, str, str]] = []
    for name in tables:
        s = ctx.stats.get(name, TableStats())
        rows.append(
            (
                name,
                str(s.read),
                str(s.inserted),
                str(s.skipped),
                str(s.media_uploaded),
            )
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(row: tuple[str, ...]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    line = "-+-".join("-" * w for w in widths)
    print()
    print(fmt(headers))
    print(line)
    for row in rows:
        print(fmt(row))
    print()
    if ctx.dry_run:
        print("(dry-run — no writes performed)")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def run_migration(args: argparse.Namespace) -> int:
    ctx = MigrationContext(
        dry_run=args.dry_run,
        skip_media=args.skip_media,
        verbose=args.verbose,
        id_map_path=Path(args.id_map).resolve(),
    )
    ctx.load_id_map()

    # --- Preflight ---
    if not legacy_settings.LEGACY_POSTGRES_URL:
        raise SystemExit(
            "LEGACY_POSTGRES_URL is not set. Add it to new_backend/.env "
            "(async or sync Postgres URL for the legacy my_website database)."
        )
    if not args.skip_media and not legacy_settings.LEGACY_MONGO_URI:
        raise SystemExit(
            "LEGACY_MONGO_URI is not set (required unless --skip-media). "
            "Add it to new_backend/.env."
        )

    legacy_engine = await _connect_legacy_pg(legacy_settings.LEGACY_POSTGRES_URL)
    new_engine, session_factory = await _connect_new_pg()

    mongo: AsyncMongoClient | None = None
    garage_client = None
    garage_cm = None

    try:
        if not args.skip_media:
            mongo = await _connect_mongo(
                legacy_settings.LEGACY_MONGO_URI,
                legacy_settings.LEGACY_MONGO_DB_NAME,
            )
            garage_client, garage_cm = await _connect_garage()
        else:
            # Still verify Garage is reachable only when we might truncate media?
            # Spec: connect to Garage in preflight always (unless skip-media implies
            # we may skip Garage). Doc: "connect to legacy Postgres, legacy Mongo,
            # new Postgres, and Garage" unless skip-media for Mongo. Connect Garage
            # always so truncate can clean objects; if skip-media and no truncate,
            # Garage is still required by the doc preflight list.
            garage_client, garage_cm = await _connect_garage()

        tables = list(MIGRATION_ORDER)
        if args.only:
            unknown = sorted(set(args.only) - set(MIGRATION_ORDER))
            if unknown:
                raise SystemExit(
                    f"Unknown --only table(s): {', '.join(unknown)}. "
                    f"Valid: {', '.join(MIGRATION_ORDER)}"
                )
            only_set = set(args.only)
            tables = [t for t in MIGRATION_ORDER if t in only_set]
        elif args.copy_all_gridfs and not args.truncate:
            tables = []

        if args.truncate:
            if args.dry_run:
                logger.info("[dry-run] would truncate: %s", ", ".join(TRUNCATE_ORDER))
            else:
                confirm = input(
                    "This will DELETE all rows from migrated tables "
                    f"({', '.join(TRUNCATE_ORDER)}) and their Garage objects. "
                    "Type 'yes' to continue: "
                )
                if confirm.strip().lower() != "yes":
                    logger.info("Truncate aborted by user")
                    return 1
                async with session_factory() as session:
                    await truncate_tables(session, garage_client)
                # Fresh id map after truncate
                ctx.id_map = {}
                ctx.save_id_map()

        for table in tables:
            migrator = MIGATORS[table]
            ctx.begin_table()
            logger.info("=== Migrating %s ===", table)

            async with session_factory() as session:
                try:
                    await migrator(
                        ctx=ctx,
                        legacy_engine=legacy_engine,
                        session=session,
                        mongo=mongo,
                        garage_client=garage_client,
                    )
                    if not ctx.dry_run:
                        await session.commit()
                        ctx.pending_id_map_keys = []
                        ctx.save_id_map()
                    logger.info(
                        "Finished %s: read=%d inserted=%d skipped=%d media=%d",
                        table,
                        ctx.stats_for(table).read,
                        ctx.stats_for(table).inserted,
                        ctx.stats_for(table).skipped,
                        ctx.stats_for(table).media_uploaded,
                    )
                except Exception:
                    logger.exception("Migration failed on table %s — rolling back", table)
                    try:
                        await session.rollback()
                    except Exception:
                        logger.exception("Rollback also failed for %s", table)
                    if garage_client is not None and ctx.uploaded_keys:
                        await _cleanup_uploaded_keys(garage_client, ctx.uploaded_keys)
                    ctx.revert_pending_id_map()
                    print_summary(ctx, tables)
                    ctx.save_id_map()
                    return 1

        print_summary(ctx, tables)
        ctx.save_id_map()

        if args.copy_all_gridfs:
            if mongo is None or garage_client is None:
                raise SystemExit("--copy-all-gridfs requires Mongo + Garage (do not pass --skip-media)")
            if args.dry_run:
                logger.info("[dry-run] would copy all GridFS files into Garage and attach profile media")
            else:
                async with session_factory() as session:
                    await copy_all_gridfs_to_garage(ctx, session, mongo, garage_client)
                    await attach_latest_profile_media(session)
                    await session.commit()

        return 0
    finally:
        await legacy_engine.dispose()
        await new_engine.dispose()
        if mongo is not None:
            await mongo.close()
        if garage_cm is not None:
            await garage_cm.__aexit__(None, None, None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate legacy portfolio Postgres + GridFS data into new_backend.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read everything and report a plan; write nothing.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete all rows from new tables first (asks to confirm).",
    )
    parser.add_argument(
        "--copy-all-gridfs",
        action="store_true",
        help="Copy every GridFS file from the reachable Mongo into Garage "
        "(hosted document store). Never writes to the source.",
    )
    parser.add_argument(
        "--skip-media",
        action="store_true",
        help="Migrate rows only; leave media FKs null.",
    )
    parser.add_argument(
        "--only",
        action="append",
        metavar="TABLE",
        help="Migrate just this table (repeatable). "
        f"One of: {', '.join(MIGRATION_ORDER)}",
    )
    parser.add_argument(
        "--id-map",
        default="./migration_id_map.json",
        help="Path to GridFS ObjectId -> media_asset_id JSON map.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser


def main() -> None:
    # Ensure we load .env from new_backend/ regardless of cwd.
    os.chdir(Path(__file__).resolve().parent)

    parser = build_parser()
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quieten noisy libs unless verbose.
    if not args.verbose:
        logging.getLogger("botocore").setLevel(logging.WARNING)
        logging.getLogger("aiobotocore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        code = asyncio.run(run_migration(args))
    except KeyboardInterrupt:
        logger.error("Interrupted")
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
