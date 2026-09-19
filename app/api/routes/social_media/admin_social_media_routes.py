from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.all_dependencies.owner_required import require_owner
from app.api.dependencies import SocialMediaServiceDep
from app.api.routes.social_media.social_media_schemas import (
    SocialMediaCreateRequest,
    SocialMediaListResponse,
    SocialMediaResponse,
    SocialMediaUpdateRequest,
)
from app.api.schemas.common import ReorderRequest

router = APIRouter(
    prefix="/admin/social-media",
    tags=["admin:social-media"],
    dependencies=[Depends(require_owner)],
)


@router.get("", response_model=SocialMediaListResponse)
async def admin_list(service: SocialMediaServiceDep) -> SocialMediaListResponse:
    return SocialMediaListResponse(items=await service.list_all())


@router.post(
    "", response_model=SocialMediaResponse, status_code=status.HTTP_201_CREATED
)
async def create_social_media(
    body: SocialMediaCreateRequest,
    service: SocialMediaServiceDep,
) -> SocialMediaResponse:
    return await service.create(body)


@router.put("/{link_id}", response_model=SocialMediaResponse)
async def update_social_media(
    link_id: UUID,
    body: SocialMediaUpdateRequest,
    service: SocialMediaServiceDep,
) -> SocialMediaResponse:
    return await service.update(link_id, body)


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_social_media(
    link_id: UUID,
    service: SocialMediaServiceDep,
) -> None:
    await service.delete(link_id)


@router.patch("/reorder", response_model=SocialMediaListResponse)
async def reorder_social_media(
    body: ReorderRequest,
    service: SocialMediaServiceDep,
) -> SocialMediaListResponse:
    return SocialMediaListResponse(items=await service.reorder(body.ids))
