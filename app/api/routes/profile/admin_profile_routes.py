from fastapi import APIRouter, Depends, File, UploadFile, status

from app.api.all_dependencies.owner_required import require_owner
from app.api.dependencies import ProfileServiceDep
from app.api.routes.profile.profile_schemas import (
    ProfileResponse,
    ProfileUpdateRequest,
)

router = APIRouter(
    prefix="/admin/profile",
    tags=["admin:profile"],
    dependencies=[Depends(require_owner)],
)


@router.put("", response_model=ProfileResponse)
async def upsert_profile(
    body: ProfileUpdateRequest,
    service: ProfileServiceDep,
) -> ProfileResponse:
    return await service.upsert(body)


@router.put("/image", response_model=ProfileResponse)
async def upload_profile_image(
    service: ProfileServiceDep,
    file: UploadFile = File(...),
) -> ProfileResponse:
    return await service.upload_image(file)


@router.delete("/image", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile_image(service: ProfileServiceDep) -> None:
    await service.delete_image()


@router.put("/resume", response_model=ProfileResponse)
async def upload_resume(
    service: ProfileServiceDep,
    file: UploadFile = File(...),
) -> ProfileResponse:
    return await service.upload_resume(file)


@router.delete("/resume", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(service: ProfileServiceDep) -> None:
    await service.delete_resume()
