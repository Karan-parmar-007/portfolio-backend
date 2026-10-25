"""One-off import of the retired all_projects app (ap_* tables) into this API.

Runs from bootstrap on every start until it succeeds once:
- serialised across instances with a transaction-level advisory lock;
- a `data_imports` row marks success, so later boots return immediately;
- everything happens in one transaction; any error rolls it back, deletes the
  images copied so far, logs, and lets the API start (retried next boot).

The ap_* rows and their apps/* images are read, never modified.
"""

from __future__ import annotations

import logging
import mimetypes
from typing import Any
from uuid import UUID

from botocore.exceptions import ClientError
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.media.media_service import MediaService
from app.api.routes.project.model import DataImport, Project, ProjectTag, ProjectTagLink
from app.api.routes.project.project_constants import ProjectStatus
from app.api.routes.project.project_schemas import optional_url
from app.api.routes.skill.model import Skill, SkillCategory
from app.core.constants import MediaKind
from app.core.errors import MediaError
from app.core.html_sanitize import sanitize_project_html

logger = logging.getLogger(__name__)

IMPORT_KEY = "all_projects_v1"
_LOCK_SQL = text("SELECT pg_advisory_xact_lock(hashtext('portfolio:data_import'))")
_MISSING_CODES = {"NoSuchKey", "404", "NotFound"}

# all_projects had five statuses; this API keeps three. Hidden is dropped.
_STATUS_MAP = {
    "live": ProjectStatus.LIVE,
    "offline": ProjectStatus.OFFLINE,
    "maintenance": ProjectStatus.OFFLINE,
    "archived": ProjectStatus.ARCHIVED,
}
_SKIP_STATUSES = {"hidden"}
_STUDIO_APPS = {"advance_scraper": "gmaps"}


class _RecordingGarage:
    """Wraps the Garage client and remembers every object this import wrote."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.written: list[tuple[str, str]] = []

    async def put_object(self, **kwargs: Any) -> Any:
        result = await self._client.put_object(**kwargs)
        self.written.append((kwargs["Bucket"], kwargs["Key"]))
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def cleanup(self) -> None:
        for bucket, key in self.written:
            try:
                await self._client.delete_object(Bucket=bucket, Key=key)
            except Exception:  # noqa: BLE001 - best effort; logged, never raised
                logger.warning("Import cleanup could not delete %s/%s", bucket, key)


async def _rows(session: AsyncSession, sql: str) -> list[Any]:
    return list((await session.execute(text(sql))).mappings().all())


class _Importer:
    def __init__(
        self,
        session: AsyncSession,
        garage: _RecordingGarage,
        *,
        source_bucket: str,
        studio_url: str,
    ) -> None:
        self.session = session
        self.garage = garage
        self.source_bucket = source_bucket
        self.studio_url = studio_url.rstrip("/")
        self.media = MediaService(pg_session=session, garage_client=garage)
        self.summary: dict[str, int] = {
            "projects": 0,
            "skipped_hidden": 0,
            "skipped_existing": 0,
            "skills": 0,
            "skill_categories": 0,
            "images": 0,
            "missing_images": 0,
        }

    async def copy_image(self, key: str | None, kind: MediaKind) -> UUID | None:
        if not key:
            return None
        try:
            obj = await self.garage.get_object(Bucket=self.source_bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING_CODES:
                logger.warning("Import: source image %s is missing; skipped", key)
                self.summary["missing_images"] += 1
                return None
            raise
        content = await obj["Body"].read()
        filename = key.rsplit("/", 1)[-1]
        content_type = obj.get("ContentType") or mimetypes.guess_type(filename)[0]
        try:
            asset = await self.media.store_bytes(
                content,
                filename=filename,
                content_type=content_type,
                kind=kind,
                commit=False,
            )
        except MediaError as exc:
            logger.warning("Import: image %s rejected (%s); skipped", key, exc.message)
            self.summary["missing_images"] += 1
            return None
        self.summary["images"] += 1
        return asset.id

    async def import_skills(self) -> None:
        ap_categories = await _rows(
            self.session,
            "SELECT id, name, sequence, show_on_home FROM ap_skill_categories ORDER BY sequence",
        )
        existing = (await self.session.execute(select(SkillCategory))).scalars().all()
        by_name = {c.name.lower(): c for c in existing}
        category_map: dict[UUID, UUID] = {}
        for row in ap_categories:
            category = by_name.get(row["name"].lower())
            if category is None:
                category = SkillCategory(name=row["name"], sequence=row["sequence"])
                self.session.add(category)
                by_name[row["name"].lower()] = category
            category.sequence = row["sequence"]
            category.show_on_home = row["show_on_home"]
            category_map[row["id"]] = category.id
            self.summary["skill_categories"] += 1
        # all_projects decided which categories are on the home page.
        if any(r["show_on_home"] for r in ap_categories):
            imported = {r["name"].lower() for r in ap_categories}
            for name, category in by_name.items():
                if name not in imported:
                    category.show_on_home = False
        await self.session.flush()

        ap_skills = await _rows(
            self.session,
            "SELECT name, category_id, sequence, icon_key, show_in_about FROM ap_skills "
            "ORDER BY sequence",
        )
        skills = {
            s.name.lower(): s
            for s in (await self.session.execute(select(Skill))).scalars().all()
        }
        for row in ap_skills:
            skill = skills.get(row["name"].lower())
            if skill is None:
                skill = Skill(name=row["name"], sequence=row["sequence"])
                self.session.add(skill)
                skills[row["name"].lower()] = skill
            skill.sequence = row["sequence"]
            skill.show_in_about = row["show_in_about"]
            skill.category_id = category_map.get(row["category_id"])
            icon_id = await self.copy_image(row["icon_key"], MediaKind.SKILL_ICON)
            if icon_id is not None:
                skill.icon_media_id = icon_id
            self.summary["skills"] += 1
        await self.session.flush()

    async def import_projects(self) -> None:
        ap_projects = await _rows(
            self.session,
            """
            SELECT p.id, p.name, p.slug, p.short_description, p.long_description,
                   p.is_featured, p.sequence, p.live_url, p.github_url, p.app_key,
                   p.cover_image_key, p.tech_stack, s.slug AS status_slug
            FROM ap_projects p JOIN ap_project_statuses s ON s.id = p.status_id
            ORDER BY p.sequence, p.name
            """,
        )
        ap_tags = await _rows(
            self.session,
            "SELECT l.project_id, t.name FROM ap_project_tag_links l "
            "JOIN ap_project_tags t ON t.id = l.tag_id ORDER BY t.name",
        )
        tags_by_project: dict[UUID, list[str]] = {}
        for row in ap_tags:
            tags_by_project.setdefault(row["project_id"], []).append(row["name"])

        taken = (
            await self.session.execute(
                select(Project.id, Project.slug, func.lower(Project.name))
            )
        ).all()
        taken_ids = {r[0] for r in taken}
        taken_slugs = {r[1] for r in taken}
        taken_names = {r[2] for r in taken}

        tag_cache = {
            t.name.lower(): t
            for t in (await self.session.execute(select(ProjectTag))).scalars().all()
        }

        for row in ap_projects:
            if row["status_slug"] in _SKIP_STATUSES:
                self.summary["skipped_hidden"] += 1
                continue
            if (
                row["id"] in taken_ids
                or row["slug"] in taken_slugs
                or row["name"].lower() in taken_names
            ):
                self.summary["skipped_existing"] += 1
                continue

            studio_slug = _STUDIO_APPS.get(row["app_key"] or "")
            if studio_slug:
                try_url = f"{self.studio_url}/products/{studio_slug}"
            else:
                try:
                    try_url = optional_url(row["live_url"])
                except ValueError:
                    try_url = None

            try:
                github_url = optional_url(row["github_url"])
            except ValueError:
                github_url = None

            project = Project(
                id=row["id"],
                name=row["name"],
                slug=row["slug"],
                short_description=row["short_description"],
                long_description=sanitize_project_html(row["long_description"]),
                status=_STATUS_MAP.get(row["status_slug"], ProjectStatus.OFFLINE).value,
                is_featured=row["is_featured"],
                sequence=row["sequence"],
                github_url=github_url,
                try_url=try_url,
                tech_stack=list(row["tech_stack"] or []),
                cover_media_id=await self.copy_image(
                    row["cover_image_key"], MediaKind.PROJECT_COVER
                ),
            )
            self.session.add(project)
            for name in tags_by_project.get(row["id"], []):
                tag = tag_cache.get(name.lower())
                if tag is None:
                    tag = ProjectTag(name=name)
                    self.session.add(tag)
                    tag_cache[name.lower()] = tag
                    await self.session.flush()
                self.session.add(ProjectTagLink(project_id=row["id"], tag_id=tag.id))
            taken_slugs.add(row["slug"])
            taken_names.add(row["name"].lower())
            self.summary["projects"] += 1
        await self.session.flush()


async def import_all_projects(
    session: AsyncSession,
    garage_client: Any,
    *,
    source_bucket: str,
    studio_url: str,
) -> dict[str, int] | None:
    """Import once. Returns the summary, or None when nothing was imported."""
    garage = _RecordingGarage(garage_client)
    try:
        await session.execute(_LOCK_SQL)
        if await session.get(DataImport, IMPORT_KEY) is not None:
            await session.rollback()
            return None
        source = (
            await session.execute(text("SELECT to_regclass('public.ap_projects')"))
        ).scalar_one_or_none()
        if source is None:
            await session.rollback()
            return None

        importer = _Importer(
            session, garage, source_bucket=source_bucket, studio_url=studio_url
        )
        await importer.import_skills()
        await importer.import_projects()
        session.add(DataImport(key=IMPORT_KEY, summary=dict(importer.summary)))
        await session.commit()
    except Exception:
        logger.exception("all_projects import failed; rolled back, will retry next start")
        await session.rollback()
        await garage.cleanup()
        return None

    logger.info("all_projects import finished: %s", importer.summary)
    return importer.summary
