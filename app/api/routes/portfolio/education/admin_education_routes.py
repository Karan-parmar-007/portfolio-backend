from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.all_dependencies.owner_required import require_owner
from app.api.dependencies import EducationServiceDep
from app.api.routes.portfolio.education.education_schemas import (
    EducationCreateRequest,
    EducationListResponse,
    EducationResponse,
    EducationUpdateRequest,
)
from app.api.schemas.common import ReorderRequest

router = APIRouter(
    prefix="/admin/education",
    tags=["admin:education"],
    dependencies=[Depends(require_owner)],
)


@router.get("", response_model=EducationListResponse)
async def admin_list_education(
    service: EducationServiceDep,
) -> EducationListResponse:
    return EducationListResponse(items=await service.list_all())


@router.post("", response_model=EducationResponse, status_code=status.HTTP_201_CREATED)
async def create_education(
    body: EducationCreateRequest,
    service: EducationServiceDep,
) -> EducationResponse:
    return await service.create(body)


@router.put("/{education_id}", response_model=EducationResponse)
async def update_education(
    education_id: UUID,
    body: EducationUpdateRequest,
    service: EducationServiceDep,
) -> EducationResponse:
    return await service.update(education_id, body)


@router.delete("/{education_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_education(
    education_id: UUID,
    service: EducationServiceDep,
) -> None:
    await service.delete(education_id)


@router.patch("/reorder", response_model=EducationListResponse)
async def reorder_education(
    body: ReorderRequest,
    service: EducationServiceDep,
) -> EducationListResponse:
    return EducationListResponse(items=await service.reorder(body.ids))
