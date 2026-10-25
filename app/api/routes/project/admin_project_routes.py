from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.all_dependencies.owner_required import require_owner
from app.api.dependencies import ProjectServiceDep
from app.api.routes.project.project_schemas import (
    ProjectCreateRequest,
    ProjectDetail,
    ProjectFeaturedRequest,
    ProjectListResponse,
    ProjectStatusRequest,
    ProjectTagCreateRequest,
    ProjectTagListResponse,
    ProjectTagResponse,
    ProjectUpdateRequest,
)
from app.api.schemas.common import ReorderRequest

router = APIRouter(
    prefix="/admin",
    tags=["admin:projects"],
    dependencies=[Depends(require_owner)],
)


@router.get("/projects", response_model=ProjectListResponse)
async def admin_list_projects(
    service: ProjectServiceDep,
    q: str | None = Query(default=None, max_length=200),
) -> ProjectListResponse:
    return ProjectListResponse(items=await service.admin_list(q=q))


@router.post("/projects", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreateRequest, service: ProjectServiceDep
) -> ProjectDetail:
    return await service.create(body)


@router.patch("/projects/reorder", response_model=ProjectListResponse)
async def reorder_projects(
    body: ReorderRequest, service: ProjectServiceDep
) -> ProjectListResponse:
    return ProjectListResponse(items=await service.reorder(body.ids))


@router.get("/projects/{project_id}", response_model=ProjectDetail)
async def admin_get_project(project_id: UUID, service: ProjectServiceDep) -> ProjectDetail:
    return await service.admin_get(project_id)


@router.put("/projects/{project_id}", response_model=ProjectDetail)
async def update_project(
    project_id: UUID, body: ProjectUpdateRequest, service: ProjectServiceDep
) -> ProjectDetail:
    return await service.update(project_id, body)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: UUID, service: ProjectServiceDep) -> None:
    await service.delete(project_id)


@router.patch("/projects/{project_id}/featured", response_model=ProjectDetail)
async def set_project_featured(
    project_id: UUID, body: ProjectFeaturedRequest, service: ProjectServiceDep
) -> ProjectDetail:
    return await service.set_featured(project_id, body.is_featured)


@router.patch("/projects/{project_id}/status", response_model=ProjectDetail)
async def set_project_status(
    project_id: UUID, body: ProjectStatusRequest, service: ProjectServiceDep
) -> ProjectDetail:
    return await service.set_status(project_id, body.status)


@router.put("/projects/{project_id}/cover", response_model=ProjectDetail)
async def upload_project_cover(
    project_id: UUID,
    service: ProjectServiceDep,
    file: UploadFile = File(...),
) -> ProjectDetail:
    return await service.set_cover(project_id, file)


@router.delete("/projects/{project_id}/cover", response_model=ProjectDetail)
async def delete_project_cover(project_id: UUID, service: ProjectServiceDep) -> ProjectDetail:
    return await service.delete_cover(project_id)


@router.get("/project-tags", response_model=ProjectTagListResponse)
async def list_project_tags(service: ProjectServiceDep) -> ProjectTagListResponse:
    return ProjectTagListResponse(items=await service.list_tags())


@router.post(
    "/project-tags", response_model=ProjectTagResponse, status_code=status.HTTP_201_CREATED
)
async def create_project_tag(
    body: ProjectTagCreateRequest, service: ProjectServiceDep
) -> ProjectTagResponse:
    return await service.create_tag(body.name)


@router.delete("/project-tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_tag(tag_id: UUID, service: ProjectServiceDep) -> None:
    await service.delete_tag(tag_id)
