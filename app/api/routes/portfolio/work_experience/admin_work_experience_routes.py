from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.all_dependencies.owner_required import require_owner
from app.api.dependencies import WorkExperienceServiceDep
from app.api.routes.portfolio.work_experience.work_experience_schemas import (
    WorkExperienceCreateRequest,
    WorkExperienceListResponse,
    WorkExperienceResponse,
    WorkExperienceUpdateRequest,
)
from app.api.schemas.common import ReorderRequest

router = APIRouter(
    prefix="/admin/work-experience",
    tags=["admin:work-experience"],
    dependencies=[Depends(require_owner)],
)


@router.get("", response_model=WorkExperienceListResponse)
async def admin_list(
    service: WorkExperienceServiceDep,
) -> WorkExperienceListResponse:
    return WorkExperienceListResponse(items=await service.list_all())


@router.post(
    "",
    response_model=WorkExperienceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_work_experience(
    body: WorkExperienceCreateRequest,
    service: WorkExperienceServiceDep,
) -> WorkExperienceResponse:
    return await service.create(body)


@router.put("/{experience_id}", response_model=WorkExperienceResponse)
async def update_work_experience(
    experience_id: UUID,
    body: WorkExperienceUpdateRequest,
    service: WorkExperienceServiceDep,
) -> WorkExperienceResponse:
    return await service.update(experience_id, body)


@router.delete("/{experience_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_experience(
    experience_id: UUID,
    service: WorkExperienceServiceDep,
) -> None:
    await service.delete(experience_id)


@router.patch("/reorder", response_model=WorkExperienceListResponse)
async def reorder_work_experience(
    body: ReorderRequest,
    service: WorkExperienceServiceDep,
) -> WorkExperienceListResponse:
    return WorkExperienceListResponse(items=await service.reorder(body.ids))
