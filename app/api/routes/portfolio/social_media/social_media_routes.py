from fastapi import APIRouter, Query

from app.api.dependencies import SocialMediaServiceDep
from app.api.routes.portfolio.social_media.social_media_schemas import SocialMediaListResponse

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/social-media", response_model=SocialMediaListResponse)
async def list_social_media(
    service: SocialMediaServiceDep,
    in_rail: bool | None = Query(default=None),
) -> SocialMediaListResponse:
    return SocialMediaListResponse(items=await service.list_all(in_rail=in_rail))
