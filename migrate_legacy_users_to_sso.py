#!/usr/bin/env python3
"""Copy legacy my-website users + roles into SSO Mongo.

Reads Neon Postgres (source, read-only). Writes only to SSO Mongo `sso_auth`.
Never deletes or updates the source.

Usage (from new_backend/):

    python migrate_legacy_users_to_sso.py
    python migrate_legacy_users_to_sso.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values
from pymongo import AsyncMongoClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import legacy_settings

logger = logging.getLogger("migrate_legacy_users_to_sso")

SSO_ENV = Path(__file__).resolve().parent.parent / "single_sign_on" / "backend" / ".env"

# SSO owner-admin routes require role name "owner".
ROLE_NAME_MAP = {
    "super_admin": "owner",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sso_mongo_settings() -> tuple[str, str]:
    values = dotenv_values(SSO_ENV)
    uri = (values.get("MONGO_URI") or "").strip()
    db_name = (values.get("MONGO_DB_NAME") or "sso_auth").strip()
    if not uri:
        raise SystemExit(f"MONGO_URI missing in {SSO_ENV}")
    return uri, db_name


async def _fetch_roles(engine) -> list[dict]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT id, name, description, created_at, updated_at FROM userrole ORDER BY name")
        )
        return [dict(row) for row in result.mappings().all()]


async def _fetch_users(engine) -> list[dict]:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                """
                SELECT u.id, u.preferred_name, u.email, u.password_hash,
                       u.email_verified, u.created_at, u.updated_at,
                       r.name AS role_name
                FROM users u
                JOIN userrole r ON r.id = u.role_id
                ORDER BY u.created_at
                """
            )
        )
        return [dict(row) for row in result.mappings().all()]


async def _ensure_role(db, name: str, created_at, updated_at) -> object:
    name = name.strip().lower()
    existing = await db.roles.find_one({"name": name})
    if existing:
        return existing["_id"]
    now = _utc_now()
    doc = {
        "name": name,
        "created_at": created_at or now,
        "updated_at": updated_at or now,
    }
    result = await db.roles.insert_one(doc)
    logger.info("Created SSO role: %s", name)
    return result.inserted_id


async def run(dry_run: bool) -> int:
    if not legacy_settings.LEGACY_POSTGRES_URL:
        raise SystemExit("LEGACY_POSTGRES_URL is not set")

    sso_uri, sso_db_name = _sso_mongo_settings()
    pg = create_async_engine(
        legacy_settings.LEGACY_POSTGRES_URL,
        echo=False,
        connect_args={
            "ssl": True,
            "statement_cache_size": 0,
            "server_settings": {"default_transaction_read_only": "on"},
        },
    )
    mongo = AsyncMongoClient(sso_uri, serverSelectionTimeoutMS=15000)
    try:
        async with pg.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Connected to source Postgres (read-only)")

        await mongo.admin.command("ping")
        db = mongo[sso_db_name]
        logger.info("Connected to SSO Mongo db=%s", sso_db_name)

        roles = await _fetch_roles(pg)
        users = await _fetch_users(pg)
        logger.info("Source roles=%d users=%d", len(roles), len(users))

        if dry_run:
            print("roles to ensure:", ", ".join(sorted({r["name"] for r in roles} | set(ROLE_NAME_MAP.values()) | {"owner", "user"})))
            print(f"users to insert or skip: {len(users)}")
            print("(dry-run — no writes)")
            return 0

        # Keep SSO's built-in roles, plus every legacy role name.
        for role in roles:
            await _ensure_role(db, role["name"], role.get("created_at"), role.get("updated_at"))
        for extra in ("owner", "user", *ROLE_NAME_MAP.values()):
            await _ensure_role(db, extra, None, None)

        role_docs = {doc["name"]: doc["_id"] async for doc in db.roles.find({})}

        inserted = 0
        skipped = 0
        for row in users:
            email = str(row["email"]).lower().strip()
            existing = await db.users.find_one({"email": email})
            if existing:
                skipped += 1
                continue

            source_role = str(row["role_name"] or "user").strip().lower()
            mapped = ROLE_NAME_MAP.get(source_role, source_role)
            role_id = role_docs.get(mapped) or role_docs.get("user")
            now = _utc_now()
            await db.users.insert_one(
                {
                    "name": row["preferred_name"],
                    "email": email,
                    "password_hash": row["password_hash"],
                    "role_id": role_id,
                    "email_verified": bool(row["email_verified"]),
                    "created_at": row.get("created_at") or now,
                    "updated_at": row.get("updated_at") or now,
                    "legacy_role_name": source_role,
                }
            )
            inserted += 1

        print(f"SSO roles now: {await db.roles.count_documents({})}")
        print(f"SSO users now: {await db.users.count_documents({})}")
        print(f"inserted={inserted} skipped_existing={skipped}")
        return 0
    finally:
        await pg.dispose()
        await mongo.close()


def main() -> None:
    os.chdir(Path(__file__).resolve().parent)
    parser = argparse.ArgumentParser(description="Copy legacy users/roles into SSO Mongo.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%H:%M:%S")
    try:
        code = asyncio.run(run(args.dry_run))
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
