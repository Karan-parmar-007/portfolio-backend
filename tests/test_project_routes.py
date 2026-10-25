"""HTTP wiring for the project API: auth, query parsing, caching, errors."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from app.api.dependencies import get_project_service
from app.api.routes.project.project_constants import ProjectStatus
from app.api.routes.project.project_schemas import (
    FacetCount,
    ProjectDetail,
    ProjectFacetsResponse,
    ProjectPage,
    ProjectSummary,
    ProjectTagResponse,
)
from app.api.schemas.pagination import PaginationParams
from app.core.errors import ConflictError, NotFoundError
from tests.conftest import FakeSso

BASE = "/api/portfolio"
PID = UUID("0192f000-0000-7000-8000-000000000001")


def _detail(**kw: Any) -> ProjectDetail:
    now = datetime.now(timezone.utc)
    data: dict[str, Any] = {
        "id": PID,
        "name": "Maps",
        "slug": "maps",
        "short_description": "d",
        "status": ProjectStatus.LIVE,
        "is_featured": False,
        "sequence": 1,
        "long_description": "<p>x</p>",
        "created_at": now,
        "updated_at": now,
    }
    data.update(kw)
    return ProjectDetail(**data)


class FakeProjectService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def list_public(self, **kw: Any) -> ProjectPage:
        self.calls.append(("list_public", kw))
        pagination: PaginationParams = kw["pagination"]
        return ProjectPage.from_page(
            [ProjectSummary(**_detail().model_dump(include=set(ProjectSummary.model_fields)))],
            total=1,
            pagination=pagination,
        )

    async def get_public(self, slug: str) -> ProjectDetail:
        if slug != "maps":
            raise NotFoundError("Project not found")
        return _detail()

    async def facets(self) -> ProjectFacetsResponse:
        return ProjectFacetsResponse(
            total=1,
            statuses=[FacetCount(value="live", count=1)],
            skills=[],
            tags=[],
        )

    async def admin_list(self, *, q: str | None) -> list[ProjectSummary]:
        self.calls.append(("admin_list", q))
        return []

    async def create(self, data: Any) -> ProjectDetail:
        self.calls.append(("create", data))
        if data.name == "dup":
            raise ConflictError("A project with this name already exists")
        return _detail(name=data.name)

    async def set_featured(self, project_id: UUID, value: bool) -> ProjectDetail:
        self.calls.append(("set_featured", (project_id, value)))
        return _detail(is_featured=value)

    async def set_status(self, project_id: UUID, status: ProjectStatus) -> ProjectDetail:
        self.calls.append(("set_status", (project_id, status)))
        return _detail(status=status)

    async def list_tags(self) -> list[ProjectTagResponse]:
        return [ProjectTagResponse(id=uuid4(), name="AI", project_count=2)]


@pytest.fixture
def fake() -> FakeProjectService:
    return FakeProjectService()


@pytest.fixture(autouse=True)
def _override(fake: FakeProjectService) -> Iterator[None]:
    from main import app

    app.dependency_overrides[get_project_service] = lambda: fake
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _owner(sso: FakeSso) -> dict[str, str]:
    sso.live_roles["owner-1"] = "owner"
    return sso.cookies(sso.mint(user_id="owner-1", email="o@example.com", role="owner"))


async def test_public_list_parses_filters_and_caches(
    app_client: httpx.AsyncClient, fake: FakeProjectService
) -> None:
    res = await app_client.get(
        f"{BASE}/portfolio/projects",
        params=[("q", "maps"), ("status", "live"), ("status", "archived"),
                ("skill", "Python"), ("tag", "AI"), ("page", "2"), ("page_size", "5")],
    )
    assert res.status_code == 200
    assert res.headers["cache-control"] == "public, max-age=60"
    name, kw = fake.calls[-1]
    assert name == "list_public"
    assert kw["q"] == "maps" and kw["skill"] == "Python" and kw["tag"] == "AI"
    assert kw["statuses"] == [ProjectStatus.LIVE, ProjectStatus.ARCHIVED]
    assert kw["pagination"].page == 2 and kw["pagination"].page_size == 5
    body = res.json()
    assert body["items"][0]["slug"] == "maps"
    assert "long_description" not in body["items"][0]


@pytest.mark.parametrize(
    "params",
    [{"status": "hidden"}, {"page": "0"}, {"page_size": "101"}, {"q": "x" * 201}],
)
async def test_public_list_rejects_bad_query(
    app_client: httpx.AsyncClient, params: dict[str, str]
) -> None:
    res = await app_client.get(f"{BASE}/portfolio/projects", params=params)
    assert res.status_code == 422


async def test_public_detail_and_404(app_client: httpx.AsyncClient) -> None:
    ok = await app_client.get(f"{BASE}/portfolio/projects/maps")
    assert ok.status_code == 200
    assert ok.json()["long_description"] == "<p>x</p>"
    assert ok.headers["cache-control"] == "public, max-age=60"
    missing = await app_client.get(f"{BASE}/portfolio/projects/nope")
    assert missing.status_code == 404


async def test_facets(app_client: httpx.AsyncClient) -> None:
    res = await app_client.get(f"{BASE}/portfolio/project-facets")
    assert res.status_code == 200
    assert res.json()["statuses"] == [{"value": "live", "count": 1}]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/projects"),
        ("POST", "/admin/projects"),
        ("GET", f"/admin/projects/{PID}"),
        ("PUT", f"/admin/projects/{PID}"),
        ("DELETE", f"/admin/projects/{PID}"),
        ("PATCH", "/admin/projects/reorder"),
        ("PATCH", f"/admin/projects/{PID}/featured"),
        ("PATCH", f"/admin/projects/{PID}/status"),
        ("PUT", f"/admin/projects/{PID}/cover"),
        ("DELETE", f"/admin/projects/{PID}/cover"),
        ("GET", "/admin/project-tags"),
        ("POST", "/admin/project-tags"),
        ("DELETE", f"/admin/project-tags/{PID}"),
    ],
)
async def test_admin_requires_owner(
    app_client: httpx.AsyncClient, sso: FakeSso, method: str, path: str
) -> None:
    res = await app_client.request(method, f"{BASE}{path}")
    assert res.status_code == 401


async def test_admin_rejects_non_owner(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    sso.live_roles["u-1"] = "user"
    cookies = sso.cookies(sso.mint(user_id="u-1", email="u@example.com"))
    res = await app_client.get(f"{BASE}/admin/projects", cookies=cookies)
    assert res.status_code == 403


async def test_admin_create_and_toggles(
    app_client: httpx.AsyncClient, sso: FakeSso, fake: FakeProjectService
) -> None:
    cookies = _owner(sso)
    headers = {"X-CSRF-Token": cookies["csrf_token"]}
    created = await app_client.post(
        f"{BASE}/admin/projects",
        json={"name": "Maps", "short_description": "d", "try_url": "https://studio.x/p"},
        cookies=cookies,
        headers=headers,
    )
    assert created.status_code == 201
    assert created.headers.get("cache-control") != "public, max-age=60"

    bad = await app_client.post(
        f"{BASE}/admin/projects",
        json={"name": "Maps", "short_description": "d", "try_url": "javascript:alert(1)"},
        cookies=cookies,
        headers=headers,
    )
    assert bad.status_code == 422

    dup = await app_client.post(
        f"{BASE}/admin/projects",
        json={"name": "dup", "short_description": "d"},
        cookies=cookies,
        headers=headers,
    )
    assert dup.status_code == 409

    featured = await app_client.patch(
        f"{BASE}/admin/projects/{PID}/featured",
        json={"is_featured": True},
        cookies=cookies,
        headers=headers,
    )
    assert featured.status_code == 200 and featured.json()["is_featured"] is True

    status = await app_client.patch(
        f"{BASE}/admin/projects/{PID}/status",
        json={"status": "archived"},
        cookies=cookies,
        headers=headers,
    )
    assert status.status_code == 200 and status.json()["status"] == "archived"


async def test_admin_mutation_needs_csrf(app_client: httpx.AsyncClient, sso: FakeSso) -> None:
    cookies = _owner(sso)
    res = await app_client.post(
        f"{BASE}/admin/projects",
        json={"name": "Maps", "short_description": "d"},
        cookies=cookies,
    )
    assert res.status_code == 403
