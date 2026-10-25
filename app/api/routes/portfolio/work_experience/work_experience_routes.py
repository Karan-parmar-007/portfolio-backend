from fastapi import APIRouter

from app.api.dependencies import WorkExperienceServiceDep
from app.api.routes.portfolio.work_experience.work_experience_schemas import (
    WorkExperienceListResponse,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/work-experience", response_model=WorkExperienceListResponse)
async def list_work_experience(
    service: WorkExperienceServiceDep,
) -> WorkExperienceListResponse:
    return WorkExperienceListResponse(items=await service.list_all())
