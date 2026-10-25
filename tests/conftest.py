"""Shared fixtures for portfolio API tests."""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from karan_sso import SsoSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import db_settings


class _AsyncBody:
    """Minimal Garage get_object Body stand-in."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self) -> bytes:
        return self._data


class FakeGarageClient:
    """In-memory Garage stub: put/get/delete/head_bucket."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.buckets: set[str] = set()

    async def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: bytes,
        ContentType: str | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        self.buckets.add(Bucket)
        self.objects[(Bucket, Key)] = {
            "Body": bytes(Body),
            "ContentType": ContentType,
        }
        return {"ETag": '"fake"'}

    async def get_object(self, *, Bucket: str, Key: str, **_kwargs: Any) -> dict[str, Any]:
        item = self.objects.get((Bucket, Key))
        if item is None:
            from botocore.exceptions import ClientError

            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": f"{Bucket}/{Key}"}},
                "GetObject",
            )
        return {
            "Body": _AsyncBody(item["Body"]),
            "ContentType": item.get("ContentType"),
            "ContentLength": len(item["Body"]),
        }

    async def delete_object(self, *, Bucket: str, Key: str, **_kwargs: Any) -> dict[str, Any]:
        self.objects.pop((Bucket, Key), None)
        return {}

    async def head_bucket(self, *, Bucket: str, **_kwargs: Any) -> dict[str, Any]:
        if Bucket not in self.buckets and not any(b == Bucket for b, _ in self.objects):
            # Allow head on configured bucket name even if empty.
            self.buckets.add(Bucket)
        return {}


class FakeGarageSession:
    """Yields a FakeGarageClient from app.state.garage_session.get_client()."""

    def __init__(self, client: FakeGarageClient) -> None:
        self._client = client

    async def get_client(self) -> AsyncIterator[FakeGarageClient]:
        yield self._client


class StubPostgresSession:
    """Placeholder so ASGI unit tests need no live Postgres at lifespan."""

    async def get_session(self) -> AsyncIterator[AsyncSession]:
        raise RuntimeError("Postgres not configured for this unit test")
        yield  # pragma: no cover

    async def verify_connection(self) -> None:
        return None

    async def dispose(self) -> None:
        return None


SSO_TEST_BASE_URL = "http://sso.test/api"
SSO_TEST_ISSUER = "https://auth.test/api/auth"


class FakeSso:
    """In-process SSO: an RSA key published as JWKS plus a scripted `/auth/me`.

    Injected into the SDK with `karan_sso.fastapi.configure(settings, http=...)`
    so tests exercise the real verifier, live check and error mapping.
    """

    def __init__(self) -> None:
        self.kid = "test-key"
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        # user_id -> live role_name; missing user -> /me answers 401
        self.live_roles: dict[str, str] = {}
        self.me_status: int | None = None  # force a status (e.g. 500 = outage)
        self.me_calls = 0
        self.transport = httpx.MockTransport(self._handle)

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def mint(self, *, user_id: str, email: str, role: str = "user") -> str:
        now = int(time.time())
        claims = {
            "iss": SSO_TEST_ISSUER,
            "aud": "karanparmar-apps",
            "sub": user_id,
            "user_id": user_id,
            "email": email,
            "name": email.split("@")[0],
            "email_verified": True,
            "role": role,
            "role_name": role,
            "roles": {},
            "sid": f"sid-{user_id}",
            "jti": secrets.token_hex(8),
            "iat": now,
            "exp": now + 900,
            "type": "access",
        }
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": self.kid})

    def cookies(self, token: str) -> dict[str, str]:
        return {"access_token": token, "csrf_token": secrets.token_urlsafe(16)}

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/auth/.well-known/jwks.json":
            return httpx.Response(200, json=self.jwks())
        if path == "/api/auth/me":
            self.me_calls += 1
            if self.me_status is not None:
                return httpx.Response(self.me_status, json={"detail": "scripted"})
            token = request.headers.get("authorization", "").removeprefix("Bearer ")
            claims = jwt.decode(token, options={"verify_signature": False})
            role = self.live_roles.get(claims["user_id"])
            if role is None:
                return httpx.Response(401, json={"detail": "Not authenticated"})
            return httpx.Response(
                200,
                json={
                    "id": claims["user_id"],
                    "email": claims["email"],
                    "name": claims.get("name"),
                    "email_verified": True,
                    "role_name": role,
                    "app_roles": {},
                },
            )
        return httpx.Response(404)


@pytest.fixture
def sso() -> Iterator[FakeSso]:
    """Point the SDK's default instance at a FakeSso; restore afterwards."""
    from karan_sso.fastapi import configure

    import main  # noqa: F401  (main configures the production instance on import)
    from app.config import auth_settings

    fake = FakeSso()
    settings = SsoSettings(
        SSO_BASE_URL=SSO_TEST_BASE_URL,
        SSO_ISSUER=SSO_TEST_ISSUER,
        SSO_AUDIENCE="karanparmar-apps",
        SSO_REQUIRE_AUDIENCE=True,
        SSO_JWT_SECRET="",
        SSO_APP_ID="portfolio",
    )
    configure(settings, http=lambda: httpx.AsyncClient(transport=fake.transport))
    try:
        yield fake
    finally:
        configure(auth_settings)


@pytest.fixture
def fake_garage_client() -> FakeGarageClient:
    return FakeGarageClient()


@pytest.fixture
async def app_client(
    fake_garage_client: FakeGarageClient,
) -> AsyncIterator[httpx.AsyncClient]:
    """ASGI client against main:app without live Postgres/Garage lifespan.

    httpx 0.28 ASGITransport does not run FastAPI lifespan, so we attach
    stub sessions on app.state for any DI that touches them.
    """
    from main import app

    app.state.postgres_session = StubPostgresSession()
    app.state.garage_session = FakeGarageSession(fake_garage_client)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Live session that rolls back; skips if Postgres is unreachable."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, OperationalError

    engine = create_async_engine(db_settings.POSTGRES_URL)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            try:
                await session.execute(text("SELECT 1"))
            except (OSError, ConnectionRefusedError, TimeoutError, OperationalError, DBAPIError) as exc:
                pytest.skip(f"Database not available: {exc}")
            yield session
            await session.rollback()
    except (OSError, ConnectionRefusedError, TimeoutError, OperationalError, DBAPIError) as exc:
        pytest.skip(f"Database not available: {exc}")
    finally:
        await engine.dispose()


@pytest.fixture
async def pg() -> AsyncIterator[AsyncSession]:
    """Live session inside one outer transaction that is always rolled back.

    Service `commit()` calls only release a SAVEPOINT, so tests can exercise
    real commits without leaving rows behind. Skips when Postgres is down or
    the 0004 projects migration has not been applied.
    """
    from sqlalchemy import text
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(db_settings.POSTGRES_URL, poolclass=NullPool)
    try:
        conn = await engine.connect()
    except Exception as exc:  # noqa: BLE001 - any connect failure means "no DB"
        await engine.dispose()
        pytest.skip(f"Database not available: {exc}")
    trans = await conn.begin()
    session = AsyncSession(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    try:
        ready = (
            await session.execute(text("SELECT to_regclass('public.data_imports')"))
        ).scalar_one_or_none()
        if ready is None:
            pytest.skip("Projects migration (0004) not applied")
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


@pytest.fixture
async def empty_projects(pg: AsyncSession) -> AsyncSession:
    """`pg` with the project tables emptied (inside the rolled-back transaction)."""
    from sqlalchemy import text

    await pg.execute(text("DELETE FROM project_tag_links"))
    await pg.execute(text("DELETE FROM projects"))
    await pg.execute(text("DELETE FROM project_tags"))
    await pg.execute(text("DELETE FROM data_imports"))
    await pg.commit()
    return pg
