from fastapi import APIRouter

from app.api.dependencies import EducationServiceDep
from app.api.routes.education.education_schemas import EducationListResponse

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/education", response_model=EducationListResponse)
async def list_education(service: EducationServiceDep) -> EducationListResponse:
    items = await service.list_all()
    return EducationListResponse(items=items)
