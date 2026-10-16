# Portfolio Backend — Agent Context

> **Read this file first**, then the relevant spec in
> [docs/portfolio-rewrite/](docs/portfolio-rewrite/README.md), before changing any
> code or answering an architecture question about this repo.

## What this is

A FastAPI backend serving a personal portfolio website and its owner-only admin
CMS. Async-first, dependency-injected, two backing stores:

| Store                | Role                          | Client                                         |
| -------------------- | ----------------------------- | ---------------------------------------------- |
| **PostgreSQL** | all relational content        | SQLAlchemy 2 async + SQLModel 0.0.38 + asyncpg |
| **Garage**     | all binaries (images, resume) | aioboto3 (path-style, SigV4)                   |

There is **no MongoDB** in this project and **no AWS S3**. Garage is a self-hosted
S3-compatible store; all object-storage code lives in `app/db/garage_session.py`
and `app/api/routes/media/`. Never use AWS-specific APIs, virtual-hosted bucket
URLs, or `list_buckets` for health checks.

Structurally this is a clone of [family_os/backend](family_os/backend). When you
need to create a file, read its counterpart there first and match it.

## Specs — the authoritative source

| Topic                              | Document                                                   |
| ---------------------------------- | ---------------------------------------------------------- |
| Overview, phases, global rules     | [README](docs/portfolio-rewrite/README.md)                  |
| Folder structure, config, layering | [01](docs/portfolio-rewrite/01-BACKEND-ARCHITECTURE.md)     |
| Tables, fields, legacy migration   | [02](docs/portfolio-rewrite/02-DATA-MODEL-AND-MIGRATION.md) |
| Every endpoint and schema          | [03](docs/portfolio-rewrite/03-API-CONTRACT.md)             |
| Auth and Garage                    | [04](docs/portfolio-rewrite/04-AUTH-AND-STORAGE.md)         |

If code and spec disagree, the spec wins — or update the spec in the same change
and say why.

## Layout

```
new_backend/
├── main.py                   # FastAPI app + lifespan (Postgres, Garage), SSO SDK config
├── karan_sso/                # VENDORED shared SSO SDK — never edit (sync from sso-backend/sdk)
├── migrate_legacy_data.py    # one-off import from the old portfolio DB + GridFS
├── app/
│   ├── config.py             # pydantic-settings: Database, Auth (extends karan_sso.SsoSettings), Cors, Media, Legacy
│   ├── api/
│   │   ├── main_router.py    # APIRouter(prefix="/api/portfolio")
│   │   ├── db_dependencies.py    # PGSessionDep, GarageClientDep
│   │   ├── dependencies.py       # service factories
│   │   ├── all_dependencies/     # owner_required.py — thin adapter over karan_sso.fastapi
│   │   ├── schemas/              # pagination.py, common.py
│   │   └── routes/<feature>/     # model.py, *_schemas.py, *_service.py, *_routes.py
│   ├── core/                 # constants.py, errors.py, slug.py
│   ├── db/                   # postgress_session.py, garage_session.py
├── migrations/               # Alembic, async env.py
└── tests/
```

Feature folders: `health`, `media`, `overview`, `profile`, `education`,
`work_experience`, `skill`, `social_media`, `project`, `contact_message`.

## Request lifecycle

```
route (*_routes.py)
  -> service dep (app/api/dependencies.py)
    -> service (*_service.py)  <- all SQL and business logic lives here
      -> db dep (app/api/db_dependencies.py)
        -> manager on app.state (app/db/*_session.py)
```

There is no repository layer. Services own their transactions: they commit and roll
back. Routes are HTTP-only.

## Startup (`main.py`)

1. Construct `PostgresSession()` and `GarageSession()`
2. `await postgres_session.verify_connection()` (`SELECT 1`)
3. Store both on `app.state`
4. Register exception handlers, add `karan_sso.fastapi.CSRFMiddleware`, then
   `CORSMiddleware` (added last so it wraps CSRF and preflights are never blocked)
5. On shutdown, dispose the Postgres engine. Garage clients are per-request.

Run: `uvicorn main:app --reload --port 8001`

## Authorisation — read this before touching any admin route

There is **no user table, no password handling, and no signup** in this backend.
Identity comes from the `single_sign_on` service (contract:
`single_sign_on/backend/docs/SSO_CONTRACT.md`) as a JWT in the `access_token`
cookie (or `Authorization: Bearer`). All verification goes through the vendored
**`karan_sso`** SDK, configured once in `main.py` with `auth_settings`
(`SSO_APP_ID=portfolio`):

- Tokens are verified locally: RS256 via SSO's JWKS (HS256 with
  `SSO_JWT_SECRET` only while the rollout lasts), `iss`/`aud` per settings.
- Admin = live global role `owner`, confirmed with SSO `GET /auth/me` using the
  access token as a bearer (30 s cache). Token role claims never grant access.
  No token / invalid / revoked → `401`, non-owner → `403`, SSO unreachable →
  `503` (never `403`).
- One guard: `require_owner` / `OwnerDep` in
  `app/api/all_dependencies/owner_required.py` (a thin re-export of
  `karan_sso.fastapi`). Declare it at **router level**:
  `APIRouter(prefix="/admin/...", dependencies=[Depends(require_owner)])`.
- This API has **no** `/auth/*` routes. The frontend calls SSO directly
  (`/api/auth/session`, `/refresh`, `/logout` — routed to SSO by Caddy in prod
  and the Vite proxy in dev). Never proxy or re-implement them here, and never
  forward the browser's Cookie header to SSO.
- CSRF: `karan_sso.fastapi.CSRFMiddleware` — double-submit (`csrf_token`
  cookie == `X-CSRF-Token` header) on every cookie-authenticated mutation, no
  Referer shortcuts. Requests without session cookies (anonymous contact form,
  bearer clients) pass. Exempt: `/health`, `/api/portfolio/health`.
- Login UI is the SSO frontend (`https://auth.karanparmar.in/login?next=...`).

## Configuration (`.env`)

**Postgres:** `POSTGRES_SERVER`, `POSTGRES_PORT`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_ECHO`

**Garage:** `GARAGE_ENDPOINT_URL`, `GARAGE_ACCESS_KEY`, `GARAGE_SECRET_KEY`,
`GARAGE_BUCKET_NAME`, `GARAGE_REGION_NAME`

**Auth (read by `karan_sso`):** `SSO_BASE_URL`, `SSO_ISSUER`, `SSO_AUDIENCE`,
`SSO_REQUIRE_AUDIENCE`, `SSO_APP_ID` (`portfolio`), `SSO_JWT_SECRET` (legacy
HS256, rollout only), `ACCESS_TOKEN_COOKIE_NAME`, `CSRF_COOKIE_NAME`,
`CSRF_HEADER_NAME`, `ENVIRONMENT` (`production` disables `/docs`, `/redoc`,
`/openapi.json`)

**CORS:** `CORS_ALLOWED_ORIGINS` — explicit list; localhost entries are dropped
when `ENVIRONMENT=production`. Allowed headers: `Content-Type`, `Authorization`,
`X-CSRF-Token`.

**Media:** `MEDIA_MAX_IMAGE_BYTES`, `MEDIA_MAX_DOCUMENT_BYTES`,
`MEDIA_ALLOWED_IMAGE_TYPES`, `MEDIA_ALLOWED_DOCUMENT_TYPES`,
`MEDIA_CACHE_MAX_AGE_SECONDS`

**Legacy import only:** `LEGACY_POSTGRES_URL`, `LEGACY_MONGO_URI`,
`LEGACY_MONGO_DB_NAME`

`.env` is gitignored. `.env.example` is committed and must list every key.

## Coding conventions

- **Async everywhere** — handlers, services, DB access.
- **SQLModel 0.0.38** — `table=True`, `__tablename__: ClassVar[str]`, no
  `SQLModelConfig` import (it is not public in this version).
- **UUIDv7 primary keys** — `Field(default_factory=uuid6.uuid7, primary_key=True)`.
- **Timezone-aware timestamps** — `DateTime(timezone=True)` with
  `server_default=func.now()` and `onupdate=func.now()`; `datetime.now(timezone.utc)`
  in Python.
- **Pydantic response models on every route.** Never return a raw dict.
- **Domain errors, not inline HTTPExceptions** — services raise from
  `app/core/errors.py`; the registered handlers map them to status codes.
- **`logging.getLogger(__name__)`**, never `print`. Never log tokens or secrets.
- **Garage naming** — `Garage*` / `garage_*` only. A single `S3` identifier is a
  review failure.
- **Bucket name is read only** inside `MediaService` and `garage_session.py`.
- **No service imports `aioboto3` or `botocore`** except through `GarageClientDep`.
- **Minimal diffs** — match the existing structure; do not refactor unrelated code.

## Media rules

- Every binary is a `media_assets` row plus one Garage object.
- Keys: `portfolio/{profile|resume|skills|projects}/{media_id}/{safe_filename}`
- Bucket is `portfolio-media`. **Never write to `my-test-bucket`** — that belongs
  to `family_os`.
- Validate content type and size before uploading; reject with a `MediaError`.
- Replacement is store-new-then-delete-old, never delete-first.
- If the Postgres commit fails after a Garage upload, `delete_object` the orphan
  before re-raising.
- Served only through `GET /api/portfolio/media/{id}` with `ETag` and immutable
  `Cache-Control`. No presigned URLs, no base64 in JSON, no encryption.

## Migrations

```bash
alembic revision --autogenerate -m "0003_short_description"
alembic upgrade head
alembic downgrade -1
```

`migrations/env.py` must import every `model.py` or autogenerate will silently drop
tables. Keep the `render_item` hook that rewrites SQLModel's `AutoString` to
`sa.String()`. The search extensions and triggers in revision `0002` are
hand-written — autogenerate cannot produce them.

## Testing

```bash
pytest                 # unit + service tests
pytest -m integration  # requires live Postgres and Garage
```

`asyncio_mode = auto`. Fixtures live in `tests/conftest.py`: `app_client`,
`db_session` (rolls back, skips if Postgres is down), `sso` (a `FakeSso`: RSA
JWKS + scripted `/auth/me`, injected via `karan_sso.fastapi.configure(settings,
http=...)`; mint tokens with `sso.mint(...)`), `fake_garage_client`.

## Common pitfalls

1. Naming anything `S3*` — this project uses Garage only.
2. Decoding JWTs or calling SSO yourself — use `karan_sso` (it handles JWKS,
   `iss`/`aud`, live checks and the 503-on-outage rule).
3. Forgetting `require_owner` on a new admin router. Declare it at router level.
4. Re-adding `/auth/session`, `/auth/refresh`, `/auth/logout` or an `/api/auth`
   mount here. The browser talks to SSO directly; this API only verifies.
5. Creating engines or boto clients outside `app/db/` — breaks lifespan and pooling.
6. Importing `SQLModelConfig` — not public in sqlmodel 0.0.38.
7. Adding a `users`, `roles`, or `permissions` table. There are none. Ever.
8. Deleting the old media before the new upload commits.
9. Writing `search_vector` from application code — it is trigger-maintained.
10. Public project endpoints forgetting the `access_levels.is_public = true` filter,
    which leaks private projects.
11. Returning `200` when a readiness check fails — it must be `503`.
12. Reintroducing the legacy quirks: `"Score"`, `ngrok_url`,
    `is_interesting_project`, `project_image_base_six_four`.

## Requirments.txt has the leatest version of the libraries, code according to them, if needed research on there docs, user dosent need outdated code
