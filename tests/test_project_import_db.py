"""One-off import of all_projects (ap_*) rows into the portfolio's tables."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import EndpointConnectionError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.project.project_import import IMPORT_KEY, import_all_projects
from tests.conftest import FakeGarageClient

SOURCE = "ap-bucket"
STUDIO = "https://studio.test"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x04\x00\x00\x00\x05" + b"\x00" * 16


async def _scalar(s: AsyncSession, sql: str, **params: Any) -> Any:
    return (await s.execute(text(sql), params)).scalar_one()


async def _rows(s: AsyncSession, sql: str, **params: Any) -> list[Any]:
    return list((await s.execute(text(sql), params)).all())


async def _add_ap_project(s: AsyncSession, name: str, status_slug: str) -> None:
    await s.execute(
        text(
            """
            INSERT INTO ap_projects (id, name, slug, short_description, long_description,
                status_id, is_featured, sequence, tech_stack, created_at, updated_at)
            SELECT gen_random_uuid(), :name, :slug, 'd', '<p>d</p>', id, false, 500,
                   '["Go"]'::jsonb, now(), now()
            FROM ap_project_statuses WHERE slug = :status
            """
        ),
        {"name": name, "slug": name.lower().replace(" ", "-"), "status": status_slug},
    )


@pytest.fixture
async def source(empty_projects: AsyncSession) -> AsyncSession:
    if await _scalar(empty_projects, "SELECT to_regclass('public.ap_projects') IS NULL"):
        pytest.skip("all_projects tables not present locally")
    await _add_ap_project(empty_projects, "Secret Hidden Thing", "hidden")
    await _add_ap_project(empty_projects, "Being Fixed", "maintenance")
    return empty_projects


def _garage_with_source_objects(keys: list[str], *, skip: set[str] = frozenset()) -> FakeGarageClient:
    garage = FakeGarageClient()
    for key in keys:
        if key not in skip:
            # Distinct bytes per object so media de-duplication does not merge them.
            garage.objects[(SOURCE, key)] = {"Body": PNG + key.encode(), "ContentType": "image/png"}
    return garage


async def _source_keys(s: AsyncSession) -> list[str]:
    rows = await _rows(
        s,
        "SELECT cover_image_key FROM ap_projects WHERE cover_image_key IS NOT NULL "
        "UNION SELECT icon_key FROM ap_skills WHERE icon_key IS NOT NULL",
    )
    return [r[0] for r in rows]


async def test_imports_everything_except_hidden(source: AsyncSession) -> None:
    keys = await _source_keys(source)
    garage = _garage_with_source_objects(keys)
    expected = await _scalar(
        source,
        "SELECT count(*) FROM ap_projects p JOIN ap_project_statuses s ON s.id = p.status_id "
        "WHERE s.slug <> 'hidden'",
    )

    summary = await import_all_projects(source, garage, source_bucket=SOURCE, studio_url=STUDIO)

    assert summary is not None and summary["projects"] == expected
    assert await _scalar(source, "SELECT count(*) FROM projects") == expected
    assert await _scalar(source, "SELECT count(*) FROM projects WHERE name = 'Secret Hidden Thing'") == 0
    assert await _scalar(source, "SELECT status FROM projects WHERE name = 'Being Fixed'") == "offline"
    # Same ids, featured flags, sequence, tech stack and tags as the source.
    mismatched = await _scalar(
        source,
        """
        SELECT count(*) FROM ap_projects a JOIN projects p ON p.id = a.id
        WHERE a.is_featured <> p.is_featured OR a.sequence <> p.sequence
           OR a.tech_stack <> p.tech_stack OR a.name <> p.name OR a.slug <> p.slug
        """,
    )
    assert mismatched == 0
    ap_links = await _scalar(
        source,
        "SELECT count(*) FROM ap_project_tag_links l JOIN projects p ON p.id = l.project_id",
    )
    assert await _scalar(source, "SELECT count(*) FROM project_tag_links") == ap_links
    covers = await _scalar(source, "SELECT count(*) FROM ap_projects a JOIN projects p ON p.id = a.id WHERE a.cover_image_key IS NOT NULL")
    assert await _scalar(source, "SELECT count(*) FROM projects WHERE cover_media_id IS NOT NULL") == covers
    # Copies land under the portfolio prefix; source objects are untouched.
    copied = [k for (b, k) in garage.objects if b != SOURCE]
    assert all(k.startswith("portfolio/") for k in copied)
    assert sum(1 for (b, _k) in garage.objects if b == SOURCE) == len(keys)
    # The scraper project now points at Studio's product page.
    scraper = await _rows(
        source,
        "SELECT p.try_url FROM projects p JOIN ap_projects a ON a.id = p.id WHERE a.app_key = 'advance_scraper'",
    )
    for (try_url,) in scraper:
        assert try_url == f"{STUDIO}/products/gmaps"
    # Skills: every ap skill exists by name with the same about flag and category.
    skill_mismatch = await _scalar(
        source,
        """
        SELECT count(*) FROM ap_skills a
        LEFT JOIN skills s ON lower(s.name) = lower(a.name)
        LEFT JOIN ap_skill_categories ac ON ac.id = a.category_id
        LEFT JOIN skill_categories sc ON sc.id = s.category_id
        WHERE s.id IS NULL OR s.show_in_about <> a.show_in_about
           OR coalesce(lower(ac.name), '') <> coalesce(lower(sc.name), '')
        """,
    )
    assert skill_mismatch == 0
    icons = await _scalar(source, "SELECT count(*) FROM ap_skills WHERE icon_key IS NOT NULL")
    assert await _scalar(
        source,
        "SELECT count(*) FROM skills s JOIN ap_skills a ON lower(a.name) = lower(s.name) "
        "WHERE a.icon_key IS NOT NULL AND s.icon_media_id IS NOT NULL",
    ) == icons
    assert await _scalar(source, "SELECT count(*) FROM data_imports WHERE key = :k", k=IMPORT_KEY) == 1


async def test_second_run_is_a_no_op(source: AsyncSession) -> None:
    garage = _garage_with_source_objects(await _source_keys(source))
    assert await import_all_projects(source, garage, source_bucket=SOURCE, studio_url=STUDIO)
    before = await _scalar(source, "SELECT count(*) FROM projects")
    objects = len(garage.objects)
    assert await import_all_projects(source, garage, source_bucket=SOURCE, studio_url=STUDIO) is None
    assert await _scalar(source, "SELECT count(*) FROM projects") == before
    assert len(garage.objects) == objects


async def test_missing_source_image_is_skipped_not_fatal(source: AsyncSession) -> None:
    keys = await _source_keys(source)
    if not keys:
        pytest.skip("no source images locally")
    garage = _garage_with_source_objects(keys, skip={keys[0]})
    summary = await import_all_projects(source, garage, source_bucket=SOURCE, studio_url=STUDIO)
    assert summary is not None and summary["missing_images"] == 1


async def test_garage_down_rolls_back_everything(source: AsyncSession) -> None:
    if not await _source_keys(source):
        pytest.skip("no source images locally")

    class DownGarage(FakeGarageClient):
        async def get_object(self, **_kw: Any) -> dict[str, Any]:
            raise EndpointConnectionError(endpoint_url="http://garage:3900")

    garage = DownGarage()
    skills_before = await _rows(source, "SELECT name, show_in_about, category_id, icon_media_id FROM skills ORDER BY name")
    assert await import_all_projects(source, garage, source_bucket=SOURCE, studio_url=STUDIO) is None
    assert await _scalar(source, "SELECT count(*) FROM projects") == 0
    assert await _scalar(source, "SELECT count(*) FROM data_imports") == 0
    assert await _rows(source, "SELECT name, show_in_about, category_id, icon_media_id FROM skills ORDER BY name") == skills_before
    assert garage.objects == {}


async def test_partial_upload_failure_cleans_up_copied_objects(source: AsyncSession) -> None:
    keys = await _source_keys(source)
    if len(keys) < 2:
        pytest.skip("need two source images")

    class FlakyGarage(FakeGarageClient):
        puts = 0

        async def put_object(self, **kw: Any) -> dict[str, Any]:
            FlakyGarage.puts += 1
            if FlakyGarage.puts == 2:
                raise EndpointConnectionError(endpoint_url="http://garage:3900")
            return await super().put_object(**kw)

    garage = FlakyGarage()
    for key in keys:
        garage.objects[(SOURCE, key)] = {"Body": PNG + key.encode(), "ContentType": "image/png"}
    assert await import_all_projects(source, garage, source_bucket=SOURCE, studio_url=STUDIO) is None
    assert [k for (b, k) in garage.objects if b != SOURCE] == []
    assert await _scalar(source, "SELECT count(*) FROM projects") == 0


async def test_no_source_tables_means_nothing_to_do(empty_projects: AsyncSession) -> None:
    if await _scalar(empty_projects, "SELECT to_regclass('public.ap_projects') IS NULL"):
        pytest.skip("all_projects tables not present locally")
    await empty_projects.execute(text("ALTER TABLE ap_projects RENAME TO ap_projects_moved"))
    result = await import_all_projects(
        empty_projects, FakeGarageClient(), source_bucket=SOURCE, studio_url=STUDIO
    )
    assert result is None
    assert await _scalar(empty_projects, "SELECT count(*) FROM data_imports") == 0


async def test_existing_project_with_same_slug_is_kept(source: AsyncSession) -> None:
    slug, name = (await _rows(source, "SELECT slug, name FROM ap_projects ORDER BY sequence LIMIT 1"))[0]
    await source.execute(
        text(
            "INSERT INTO projects (id, name, slug, short_description, long_description, status) "
            "VALUES (gen_random_uuid(), :n, :s, 'mine', '<p></p>', 'live')"
        ),
        {"n": name + " (mine)", "s": slug},
    )
    garage = _garage_with_source_objects(await _source_keys(source))
    summary = await import_all_projects(source, garage, source_bucket=SOURCE, studio_url=STUDIO)
    assert summary is not None and summary["skipped_existing"] == 1
    assert await _scalar(source, "SELECT short_description FROM projects WHERE slug = :slug", slug=slug) == "mine"
