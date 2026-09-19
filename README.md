# Portfolio API

FastAPI backend for karanparmar.in. Structure mirrors `family_os/backend`.

## Quick start

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill secrets — SSO_JWT_SECRET must match SSO JWT_SECRET
alembic upgrade head
uvicorn main:app --reload --port 8001
```

Verify: `curl http://localhost:8001/api/v1/health/ready`

## Agent rules

Read [AGENTS.md](AGENTS.md) and [docs/portfolio-rewrite/](../docs/portfolio-rewrite/README.md) before changing code.

## Ports

| Service | Port |
|---|---|
| This API | 8001 |
| SSO API | 8000 |
| Portfolio frontend | 5174 |
| Postgres | 5433 |
| Garage | 3900 |

## Auth

No local users. Admin gates on SSO live role (`GET /auth/me` → `role_name == owner`)
after local JWT verify. Login is on the SSO frontend; refresh/logout are proxied
through this API. See [04-AUTH-AND-STORAGE.md](../docs/portfolio-rewrite/04-AUTH-AND-STORAGE.md).

## Legacy data migration

One-off import from the old Postgres DB + Mongo GridFS into this API's schema and
Garage bucket `portfolio-media`. Requires `LEGACY_POSTGRES_URL` and (unless
skipping media) `LEGACY_MONGO_URI` in `.env`. Full behaviour is in
[02-DATA-MODEL-AND-MIGRATION.md](../docs/portfolio-rewrite/02-DATA-MODEL-AND-MIGRATION.md) §6.

From `new_backend/`:

```bash
# Plan only — no writes
python migrate_legacy_data.py --dry-run

# Full import
python migrate_legacy_data.py --verbose

# Rows only (leave media FKs null)
python migrate_legacy_data.py --skip-media

# Subset of tables (repeatable)
python migrate_legacy_data.py --only access_levels --only projects

# Wipe new tables first (interactive confirm), then import
python migrate_legacy_data.py --truncate

# Custom id-map path (default ./migration_id_map.json)
python migrate_legacy_data.py --id-map ./migration_id_map.json
```

Do **not** point Garage at `my-test-bucket` — use the dedicated `portfolio-media`
bucket.

## Tests

```bash
pytest tests/ -q
# Unit-only examples (no live DB):
pytest tests/test_slug.py tests/test_auth_owner_gate.py -q
```

Integration tests are marked `@pytest.mark.integration` and skip when Postgres
is unreachable.

## Docker

```bash
docker build -t portfolio-api .
docker run --env-file .env -p 8001:8001 portfolio-api
```

Run `alembic upgrade head` against the target database before serving traffic
(or from a one-shot migration job). The image starts uvicorn on port 8001.
