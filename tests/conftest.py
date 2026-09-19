"""Shared fixtures for portfolio API tests."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.auth_cookies import ACCESS_TOKEN_COOKIE, CSRF_TOKEN_COOKIE
from app.config import auth_settings, db_settings


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
            raise KeyError(f"NoSuchKey: {Bucket}/{Key}")
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


def _mint_access_token(
    *,
    email: str,
    user_id: str = "test-user",
    role_name: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "access",
        "user_id": user_id,
        "email": email,
        "exp": now + timedelta(hours=1),
    }
    if role_name:
        payload["role_name"] = role_name
    return jwt.encode(
        payload,
        auth_settings.SSO_JWT_SECRET,
        algorithm=auth_settings.SSO_JWT_ALGORITHM,
    )


@pytest.fixture
def fake_garage_client() -> FakeGarageClient:
    return FakeGarageClient()


@pytest.fixture
def owner_cookies() -> dict[str, str]:
    token = _mint_access_token(email="owner@example.com", user_id="owner-1")
    return {
        ACCESS_TOKEN_COOKIE: token,
        CSRF_TOKEN_COOKIE: secrets.token_urlsafe(16),
    }


@pytest.fixture
def owner_role_cookies() -> dict[str, str]:
    token = _mint_access_token(
        email="role-owner@example.com",
        user_id="role-owner-1",
        role_name="owner",
    )
    return {
        ACCESS_TOKEN_COOKIE: token,
        CSRF_TOKEN_COOKIE: secrets.token_urlsafe(16),
    }


@pytest.fixture
def non_owner_cookies() -> dict[str, str]:
    token = _mint_access_token(email="other@example.com", user_id="other-1")
    return {
        ACCESS_TOKEN_COOKIE: token,
        CSRF_TOKEN_COOKIE: secrets.token_urlsafe(16),
    }


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
