"""ProjectService against the real Postgres schema (rolled back after each test)."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from fastapi import UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from app.api.routes.project.project_constants import MAX_FEATURED_PROJECTS, ProjectStatus
from app.api.routes.project.project_schemas import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
)
from app.api.routes.project.project_service import ProjectService
from app.api.schemas.pagination import PaginationParams
from app.core.errors import ConflictError, NotFoundError, ValidationError
from tests.conftest import FakeGarageClient

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x03" + b"\x00" * 32


@pytest.fixture
def garage() -> FakeGarageClient:
    return FakeGarageClient()


@pytest.fixture
def svc(empty_projects: AsyncSession, garage: FakeGarageClient) -> ProjectService:
    return ProjectService(pg_session=empty_projects, garage_client=garage)


def _body(name: str, **kw: object) -> ProjectCreateRequest:
    data: dict[str, object] = {"name": name, "short_description": f"{name} desc"}
    data.update(kw)
    return ProjectCreateRequest.model_validate(data)


def _page(page: int = 1, size: int = 20) -> PaginationParams:
    return PaginationParams(page=page, page_size=size)


async def test_create_sanitizes_and_slugs(svc: ProjectService) -> None:
    created = await svc.create(
        _body(
            "Maps Scraper!",
            long_description='<p onclick="x()">hi</p><script>bad()</script>',
            tech_stack=["Python", "FastAPI"],
            tags=["AI", "Tools"],
        )
    )
    assert created.slug == "maps-scraper"
    assert "script" not in created.long_description
    assert "onclick" not in created.long_description
    assert created.tech_stack == ["Python", "FastAPI"]
    assert created.tags == ["AI", "Tools"]
    assert created.sequence == 1
    again = await svc.create(_body("Second"))
    assert again.sequence == 2


async def test_duplicate_name_is_conflict_case_insensitive(svc: ProjectService) -> None:
    await svc.create(_body("Maps"))
    with pytest.raises(ConflictError):
        await svc.create(_body("maps"))


async def test_slug_collision_gets_suffix(svc: ProjectService) -> None:
    await svc.create(_body("Maps Tool"))
    other = await svc.create(_body("Maps-Tool"))
    assert other.slug == "maps-tool-2"


async def test_rename_updates_slug_and_keeps_it_unique(svc: ProjectService) -> None:
    a = await svc.create(_body("Alpha"))
    await svc.create(_body("Beta"))
    renamed = await svc.update(a.id, ProjectUpdateRequest(name="Beta Two"))
    assert renamed.slug == "beta-two"
    with pytest.raises(ConflictError):
        await svc.update(a.id, ProjectUpdateRequest(name="BETA"))


async def test_featured_first_any_status_then_sequence(svc: ProjectService) -> None:
    a = await svc.create(_body("A live", status="live"))
    b = await svc.create(_body("B archived featured", status="archived", is_featured=True))
    c = await svc.create(_body("C offline"))
    page = await svc.list_public(q=None, statuses=[], skill=None, tag=None, pagination=_page())
    assert [p.id for p in page.items] == [b.id, a.id, c.id]
    assert page.total == 3


async def test_featured_cap(svc: ProjectService) -> None:
    for i in range(MAX_FEATURED_PROJECTS):
        await svc.create(_body(f"F{i}", is_featured=True))
    with pytest.raises(ConflictError):
        await svc.create(_body("one too many", is_featured=True))
    extra = await svc.create(_body("not featured"))
    with pytest.raises(ConflictError):
        await svc.set_featured(extra.id, True)
    # Re-saving an already featured project must not trip the cap.
    first = (await svc.admin_list(q=None))[0]
    assert (await svc.set_featured(first.id, True)).is_featured is True
    assert (await svc.set_featured(first.id, False)).is_featured is False
    assert (await svc.set_featured(extra.id, True)).is_featured is True


async def test_filters_search_status_skill_tag(svc: ProjectService) -> None:
    await svc.create(_body("Maps Scraper", status="live", tech_stack=["Python"], tags=["Data"]))
    await svc.create(_body("Chat Bot", status="archived", tech_stack=["TypeScript"], tags=["AI"]))
    await svc.create(_body("Vision", status="offline", tech_stack=["Python", "PyTorch"]))

    async def names(**kw: object) -> list[str]:
        args: dict[str, object] = {"q": None, "statuses": [], "skill": None, "tag": None}
        args.update(kw)
        page = await svc.list_public(pagination=_page(), **args)  # type: ignore[arg-type]
        return sorted(p.name for p in page.items)

    assert await names(q="scrap") == ["Maps Scraper"]
    assert await names(q="pytorch") == ["Vision"]  # tech stack is searchable
    assert await names(q="CHAT") == ["Chat Bot"]
    assert await names(q="%") == []  # LIKE wildcards are literal
    assert await names(q="_") == []
    assert await names(statuses=[ProjectStatus.LIVE, ProjectStatus.OFFLINE]) == [
        "Maps Scraper",
        "Vision",
    ]
    assert await names(skill="Python") == ["Maps Scraper", "Vision"]
    assert await names(skill="python") == []  # exact facet value
    assert await names(tag="AI") == ["Chat Bot"]
    assert await names(tag="ai") == ["Chat Bot"]
    assert await names(skill="Python", statuses=[ProjectStatus.LIVE]) == ["Maps Scraper"]


async def test_pagination_total_past_the_end(svc: ProjectService) -> None:
    for i in range(5):
        await svc.create(_body(f"P{i}"))
    page2 = await svc.list_public(q=None, statuses=[], skill=None, tag=None, pagination=_page(2, 2))
    assert len(page2.items) == 2 and page2.total == 5 and page2.total_pages == 3
    past = await svc.list_public(q=None, statuses=[], skill=None, tag=None, pagination=_page(9, 2))
    assert past.items == [] and past.total == 5


async def test_try_url_only_public_when_live(svc: ProjectService) -> None:
    url = "https://studio.karanparmar.in/products/gmaps"
    live = await svc.create(_body("Live one", status="live", try_url=url))
    old = await svc.create(_body("Old one", status="archived", try_url=url))
    assert (await svc.get_public(live.slug)).try_url == url
    assert (await svc.get_public(old.slug)).try_url is None
    assert (await svc.admin_get(old.id)).try_url == url


async def test_get_public_missing(svc: ProjectService) -> None:
    with pytest.raises(NotFoundError):
        await svc.get_public("nope")


async def test_facets(svc: ProjectService) -> None:
    await svc.create(_body("A", status="live", tech_stack=["Python", "FastAPI"], tags=["AI"]))
    await svc.create(_body("B", status="archived", tech_stack=["Python"], tags=["AI", "Web"]))
    facets = await svc.facets()
    assert facets.total == 2
    assert {f.value: f.count for f in facets.statuses} == {"live": 1, "offline": 0, "archived": 1}
    assert facets.skills[0].value == "Python" and facets.skills[0].count == 2
    assert {f.value: f.count for f in facets.tags} == {"AI": 2, "Web": 1}


async def test_update_partial_and_clear_urls(svc: ProjectService) -> None:
    p = await svc.create(_body("P", github_url="https://github.com/x/y", tags=["AI"]))
    updated = await svc.update(p.id, ProjectUpdateRequest.model_validate({"github_url": None}))
    assert updated.github_url is None
    assert updated.tags == ["AI"]  # untouched fields stay
    updated = await svc.update(p.id, ProjectUpdateRequest(tags=[]))
    assert updated.tags == []


async def test_status_change(svc: ProjectService) -> None:
    p = await svc.create(_body("P"))
    assert (await svc.set_status(p.id, ProjectStatus.ARCHIVED)).status is ProjectStatus.ARCHIVED
    with pytest.raises(NotFoundError):
        await svc.set_status(uuid4(), ProjectStatus.LIVE)


async def test_reorder_requires_every_id(svc: ProjectService) -> None:
    a = await svc.create(_body("A"))
    b = await svc.create(_body("B"))
    with pytest.raises(ValidationError):
        await svc.reorder([a.id])
    items = await svc.reorder([b.id, a.id])
    assert [i.id for i in items] == [b.id, a.id]


async def test_cover_upload_replace_delete(
    svc: ProjectService, garage: FakeGarageClient
) -> None:
    p = await svc.create(_body("P"))

    def upload(data: bytes) -> UploadFile:
        return UploadFile(
            file=io.BytesIO(data),
            filename="cover.png",
            headers=Headers({"content-type": "image/png"}),
        )

    first = await svc.set_cover(p.id, upload(PNG))
    assert first.cover is not None and first.cover.width == 2
    assert len(garage.objects) == 1
    second = await svc.set_cover(p.id, upload(PNG + b"x"))
    assert second.cover is not None and second.cover.id != first.cover.id
    assert len(garage.objects) == 1  # old object removed after the swap
    cleared = await svc.delete_cover(p.id)
    assert cleared.cover is None
    assert garage.objects == {}


async def test_delete_removes_project_tags_links_and_cover(
    svc: ProjectService, empty_projects: AsyncSession
) -> None:
    p = await svc.create(_body("P", tags=["AI"]))
    await svc.delete(p.id)
    with pytest.raises(NotFoundError):
        await svc.admin_get(p.id)
    links = (await empty_projects.execute(text("SELECT count(*) FROM project_tag_links"))).scalar_one()
    assert links == 0
    with pytest.raises(NotFoundError):
        await svc.delete(p.id)


async def test_tags_crud(svc: ProjectService) -> None:
    await svc.create(_body("P", tags=["AI"]))
    tag = await svc.create_tag("Web")
    with pytest.raises(ConflictError):
        await svc.create_tag("web")
    tags = {t.name: t.project_count for t in await svc.list_tags()}
    assert tags == {"AI": 1, "Web": 0}
    await svc.delete_tag(tag.id)
    with pytest.raises(NotFoundError):
        await svc.delete_tag(tag.id)


async def test_overview_lists(svc: ProjectService) -> None:
    await svc.create(_body("F", is_featured=True, status="archived"))
    for i in range(8):
        await svc.create(_body(f"O{i}"))
    featured, others, total = await svc.overview_lists()
    assert [p.name for p in featured] == ["F"]
    assert len(others) == 6 and all(not p.is_featured for p in others)
    assert total == 9


async def test_shared_cover_survives_other_projects_changes(
    svc: ProjectService, garage: FakeGarageClient
) -> None:
    """Identical uploads share one media row; releasing it must not orphan others."""

    def upload() -> UploadFile:
        return UploadFile(
            file=io.BytesIO(PNG),
            filename="same.png",
            headers=Headers({"content-type": "image/png"}),
        )

    a = await svc.create(_body("A"))
    b = await svc.create(_body("B"))
    await svc.set_cover(a.id, upload())
    b_cover = (await svc.set_cover(b.id, upload())).cover
    await svc.delete_cover(a.id)
    assert (await svc.admin_get(b.id)).cover == b_cover
    assert len(garage.objects) == 1
    await svc.delete(b.id)
    assert garage.objects == {}
