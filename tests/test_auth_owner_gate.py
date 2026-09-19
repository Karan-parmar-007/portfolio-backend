"""Owner-gate and session endpoint tests (no live DB required)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest


@pytest.mark.asyncio
async def test_session_unauthenticated(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/api/portfolio/auth/session")
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is False
    assert body["is_owner"] is False
    assert body["email"] is None
    assert body["user_id"] is None
    assert body["role_name"] is None
    assert body["name"] is None


@pytest.mark.asyncio
async def test_session_owner_via_live_role(
    app_client: httpx.AsyncClient,
    owner_cookies: dict[str, str],
) -> None:
    with patch(
        "app.api.all_dependencies.owner_required.fetch_sso_me",
        new=AsyncMock(
            return_value={
                "id": "owner-1",
                "email": "owner@example.com",
                "role_name": "owner",
                "name": "Karan Parmar",
            }
        ),
    ):
        app_client.cookies.update(owner_cookies)
        response = await app_client.get("/api/portfolio/auth/session")
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["is_owner"] is True
    assert body["email"] == "owner@example.com"
    assert body["user_id"] == "owner-1"
    assert body["role_name"] == "owner"
    assert body["name"] == "Karan Parmar"


@pytest.mark.asyncio
async def test_session_non_owner(
    app_client: httpx.AsyncClient,
    non_owner_cookies: dict[str, str],
) -> None:
    with patch(
        "app.api.all_dependencies.owner_required.fetch_sso_me",
        new=AsyncMock(
            return_value={
                "id": "other-1",
                "email": "other@example.com",
                "role_name": "user",
            }
        ),
    ):
        app_client.cookies.update(non_owner_cookies)
        response = await app_client.get("/api/portfolio/auth/session")
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["is_owner"] is False
    assert body["email"] == "other@example.com"
    assert body["role_name"] == "user"


@pytest.mark.asyncio
async def test_session_jwt_role_claim_ignored(
    app_client: httpx.AsyncClient,
    owner_role_cookies: dict[str, str],
) -> None:
    """role_name in the JWT must not grant admin — only live SSO /me."""
    with patch(
        "app.api.all_dependencies.owner_required.fetch_sso_me",
        new=AsyncMock(
            return_value={
                "id": "role-owner-1",
                "email": "role-owner@example.com",
                "role_name": "user",
            }
        ),
    ):
        app_client.cookies.update(owner_role_cookies)
        response = await app_client.get("/api/portfolio/auth/session")
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["is_owner"] is False
    assert body["role_name"] == "user"


@pytest.mark.asyncio
async def test_admin_route_401_without_cookie(app_client: httpx.AsyncClient) -> None:
    """OwnerDep runs before service DI — 401 without needing Postgres."""
    response = await app_client.get("/api/portfolio/admin/education")
    assert response.status_code == 401
    assert "detail" in response.json()


@pytest.mark.asyncio
async def test_admin_route_403_for_non_owner(
    app_client: httpx.AsyncClient,
    non_owner_cookies: dict[str, str],
) -> None:
    with patch(
        "app.api.all_dependencies.owner_required.fetch_sso_me",
        new=AsyncMock(
            return_value={
                "id": "other-1",
                "email": "other@example.com",
                "role_name": "user",
            }
        ),
    ):
        app_client.cookies.update(non_owner_cookies)
        response = await app_client.get("/api/portfolio/admin/education")
    assert response.status_code == 403
    assert "detail" in response.json()
