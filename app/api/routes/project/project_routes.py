from fastapi import APIRouter, Query, Response

from app.api.dependencies import ProjectServiceDep
from app.api.routes.project.project_constants import PUBLIC_CACHE_CONTROL, ProjectStatus
from app.api.routes.project.project_schemas import (
    ProjectDetail,
    ProjectFacetsResponse,
    ProjectPage,
)
from app.api.schemas.pagination import PaginationDep

router = APIRouter(prefix="/portfolio", tags=["portfolio:projects"])


@router.get("/projects", response_model=ProjectPage)
async def list_projects(
    response: Response,
    service: ProjectServiceDep,
    pagination: PaginationDep,
    q: str | None = Query(default=None, max_length=200),
    status: list[ProjectStatus] = Query(default_factory=list),
    skill: str | None = Query(default=None, max_length=50),
    tag: str | None = Query(default=None, max_length=50),
) -> ProjectPage:
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
    return await service.list_public(
        q=q, statuses=status, skill=skill, tag=tag, pagination=pagination
    )


@router.get("/project-facets", response_model=ProjectFacetsResponse)
async def project_facets(
    response: Response, service: ProjectServiceDep
) -> ProjectFacetsResponse:
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
    return await service.facets()


@router.get("/projects/{slug}", response_model=ProjectDetail)
async def get_project(
    slug: str, response: Response, service: ProjectServiceDep
) -> ProjectDetail:
    response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL
    return await service.get_public(slug)
