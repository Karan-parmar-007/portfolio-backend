"""Auth integration tests: owner gate, CSRF and the public contact form.

The real `karan_sso` SDK runs against an in-process SSO (RSA JWKS + scripted
`/auth/me`, see `FakeSso` in conftest). No live Postgres or SSO required —
services are replaced with fakes via dependency overrides.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.api.dependencies import get_contact_message_service, get_education_service
from tests.conftest import FakeSso

ADMIN_URL = "/api/portfolio/admin/education"


class FakeEducationService:
    async def list_all(self) -> list[Any]:
        return []

    async def reorder(self, ids: list[Any]) -> list[Any]:
        return []


class FakeContactService:
    def __init__(self) -> None:
        self.created: list[Any] = []

    async def create(self, body: Any) -> None:
        self.created.append(body)


@pytest.fixture
def fake_contact() -> FakeContactService:
    return FakeContactService()


@pytest.fixture(autouse=True)
def _service_overrides(fake_contact: FakeContactService) -> Iterator[None]:
    from main import app

    app.dependency_overrides[get_education_service] = FakeEducationService
    app.dependency_overrides[get_contact_message_service] = lambda: fake_contact
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _owner(sso: FakeSso) -> dict[str, str]:
    sso.live_roles["owner-1"] = "owner"
    return sso.cookies(sso.mint(user_id="owner-1", email="owner@example.com", role="owner"))


# -- owner gate ------------------------------------------------------------


async def test_admin_401_without_token(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    response = await app_client.get(ADMIN_URL)
    assert response.status_code == 401
    assert sso.me_calls == 0


async def test_admin_401_with_garbage_token(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    app_client.cookies.update({"access_token": "not-a-jwt"})
    response = await app_client.get(ADMIN_URL)
    assert response.status_code == 401


async def test_admin_403_for_non_owner(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    sso.live_roles["user-1"] = "user"
    app_client.cookies.update(sso.cookies(sso.mint(user_id="user-1", email="u@example.com")))
    response = await app_client.get(ADMIN_URL)
    assert response.status_code == 403
    assert sso.me_calls == 1


async def test_admin_403_when_token_claims_owner_but_live_role_is_user(
    app_client: httpx.AsyncClient, sso: FakeSso
) -> None:
    """A stale `owner` claim in the token never grants access — live /me wins."""
    sso.live_roles["demoted-1"] = "user"
    token = sso.mint(user_id="demoted-1", email="d@example.com", role="owner")
    app_client.cookies.update(sso.cookies(token))
    response = await app_client.get(ADMIN_URL)
    assert response.status_code == 403


async def test_admin_200_for_owner(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    app_client.cookies.update(_owner(sso))
    response = await app_client.get(ADMIN_URL)
    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_admin_200_for_owner_with_bearer(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    sso.live_roles["owner-1"] = "owner"
    token = sso.mint(user_id="owner-1", email="owner@example.com", role="owner")
    response = await app_client.get(ADMIN_URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


async def test_admin_401_when_sso_revoked_session(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    # Valid signature, but SSO /me says the session is gone (no live role).
    app_client.cookies.update(sso.cookies(sso.mint(user_id="gone-1", email="g@example.com")))
    response = await app_client.get(ADMIN_URL)
    assert response.status_code == 401


async def test_admin_503_when_sso_me_fails(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    app_client.cookies.update(_owner(sso))
    sso.me_status = 500
    response = await app_client.get(ADMIN_URL)
    assert response.status_code == 503


# -- CSRF ------------------------------------------------------------------


async def test_csrf_403_on_cookie_mutation_without_header(
    app_client: httpx.AsyncClient, sso: FakeSso
) -> None:
    app_client.cookies.update(_owner(sso))
    response = await app_client.patch(f"{ADMIN_URL}/reorder", json={"ids": []})
    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF token missing or invalid"


async def test_csrf_403_with_docs_referer(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    """The old Referer '/docs' bypass is gone."""
    app_client.cookies.update(_owner(sso))
    response = await app_client.patch(
        f"{ADMIN_URL}/reorder",
        json={"ids": []},
        headers={"Referer": "http://test/docs"},
    )
    assert response.status_code == 403


async def test_csrf_passes_with_matching_header(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    cookies = _owner(sso)
    app_client.cookies.update(cookies)
    response = await app_client.patch(
        f"{ADMIN_URL}/reorder",
        json={"ids": [str(uuid4())]},
        headers={"X-CSRF-Token": cookies["csrf_token"]},
    )
    assert response.status_code == 200


# -- public contact form ---------------------------------------------------

CONTACT = {
    "name": "Visitor",
    "email": "visitor@example.com",
    "subject": "Hello",
    "message": "Nice site",
}


async def test_contact_anonymous_post_works(
    app_client: httpx.AsyncClient, sso: FakeSso, fake_contact: FakeContactService
) -> None:
    response = await app_client.post("/api/portfolio/contact", json=CONTACT)
    assert response.status_code == 201
    assert len(fake_contact.created) == 1


async def test_contact_signed_in_post_with_csrf_header(
    app_client: httpx.AsyncClient, sso: FakeSso, fake_contact: FakeContactService
) -> None:
    cookies = sso.cookies(sso.mint(user_id="user-1", email="u@example.com"))
    app_client.cookies.update(cookies)
    response = await app_client.post(
        "/api/portfolio/contact",
        json=CONTACT,
        headers={"X-CSRF-Token": cookies["csrf_token"]},
    )
    assert response.status_code == 201


# -- removed proxies -------------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/portfolio/auth/session"),
        ("POST", "/api/portfolio/auth/refresh"),
        ("POST", "/api/portfolio/auth/logout"),
        ("POST", "/api/auth/refresh"),
        ("POST", "/api/auth/logout"),
    ],
)
async def test_auth_proxies_removed(
    app_client: httpx.AsyncClient, sso: FakeSso, method: str, path: str
) -> None:
    response = await app_client.request(method, path)
    assert response.status_code in (404, 405)
