from fastapi import APIRouter

from app.api.dependencies import ProfileServiceDep
from app.api.routes.portfolio.profile.profile_schemas import ProfileResponse

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(service: ProfileServiceDep) -> ProfileResponse:
    return await service.get_public()
