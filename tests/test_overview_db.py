"""The home page's single request carries skills and projects again."""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.portfolio.overview.overview_service import OverviewService
from app.api.routes.project.project_schemas import ProjectCreateRequest
from app.api.routes.project.project_service import ProjectService
from app.api.routes.skill.skill_service import SkillService
from tests.conftest import FakeGarageClient


async def test_overview_includes_projects_and_skills(empty_projects: AsyncSession) -> None:
    garage = FakeGarageClient()
    projects = ProjectService(pg_session=empty_projects, garage_client=garage)
    await projects.create(
        ProjectCreateRequest(name="Old but cool", short_description="d", status="archived", is_featured=True)
    )
    await projects.create(ProjectCreateRequest(name="Plain", short_description="d"))

    overview = await OverviewService(empty_projects, garage).get_overview()

    assert [p.name for p in overview.featured_projects] == ["Old but cool"]
    assert [p.name for p in overview.projects] == ["Plain"]
    assert overview.project_count == 2
    home_categories = (
        await empty_projects.execute(text("SELECT count(*) FROM skill_categories WHERE show_on_home"))
    ).scalar_one()
    assert len(overview.skill_categories) == min(home_categories, 3)
    about = (
        await empty_projects.execute(text("SELECT count(*) FROM skills WHERE show_in_about"))
    ).scalar_one()
    assert len(overview.about_skills) == about


async def test_skill_listing_query_count_is_constant(pg: AsyncSession) -> None:
    """Icons load in one batch, not one query per skill (no N+1)."""
    statements: list[str] = []
    sync_engine = pg.bind.sync_engine  # type: ignore[union-attr]

    def count(*_args: object) -> None:
        statements.append("q")

    event.listen(sync_engine, "before_cursor_execute", count)
    try:
        skills = await SkillService(pg, FakeGarageClient()).list_skills()
        categories = await SkillService(pg, FakeGarageClient()).list_categories()
    finally:
        event.remove(sync_engine, "before_cursor_execute", count)
    assert len(skills) >= 1 and len(categories) >= 1
    assert len(statements) <= 7
