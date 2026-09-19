from __future__ import annotations

import logging
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.media.media_schemas import MediaRef, media_asset_to_ref
from app.api.routes.media.media_service import MediaService
from app.api.routes.media.model import MediaAsset
from app.api.routes.profile.model import ProfileInfo
from app.api.routes.profile.profile_schemas import (
    ProfileResponse,
    ProfileUpdateRequest,
)
from app.core.constants import MediaKind
from app.core.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)


class ProfileService:
    def __init__(self, pg_session: AsyncSession, garage_client: object) -> None:
        self.pg_session = pg_session
        self.media = MediaService(pg_session=pg_session, garage_client=garage_client)

    async def _get_row(self) -> ProfileInfo | None:
        return (
            await self.pg_session.execute(select(ProfileInfo).limit(1))
        ).scalar_one_or_none()

    async def _media_ref(self, media_id: UUID | None) -> MediaRef | None:
        if media_id is None:
            return None
        asset = (
            await self.pg_session.execute(
                select(MediaAsset).where(MediaAsset.id == media_id)
            )
        ).scalar_one_or_none()
        return media_asset_to_ref(asset)

    async def to_response(self, row: ProfileInfo) -> ProfileResponse:
        return ProfileResponse(
            name=row.name,
            headline=row.headline,
            hero_greeting=row.hero_greeting,
            about=row.about,
            email=row.email,
            phone=row.phone,
            location=row.location,
            available_for_work=row.available_for_work,
            profile_image=await self._media_ref(row.profile_image_media_id),
            resume=await self._media_ref(row.resume_media_id),
        )

    async def get_public(self) -> ProfileResponse:
        row = await self._get_row()
        if row is None:
            raise NotFoundError("Profile not found")
        return await self.to_response(row)

    async def upsert(self, data: ProfileUpdateRequest) -> ProfileResponse:
        row = await self._get_row()
        payload = data.model_dump(exclude_unset=True)
        if row is None:
            if "name" not in payload or "email" not in payload:
                raise ValidationError(
                    "Profile does not exist; name and email are required to create it"
                )
            row = ProfileInfo(
                name=payload.pop("name"),
                email=payload.pop("email"),
                **payload,
            )
            self.pg_session.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return await self.to_response(row)

    async def upload_image(self, file: UploadFile) -> ProfileResponse:
        row = await self._get_row()
        if row is None:
            raise NotFoundError("Profile not found")
        old_id = row.profile_image_media_id
        asset = await self.media.store(file, MediaKind.PROFILE_IMAGE)
        row.profile_image_media_id = asset.id
        try:
            await self.pg_session.commit()
            await self.pg_session.refresh(row)
        except Exception:
            await self.pg_session.rollback()
            if asset.id != old_id:
                await self.media.delete(asset.id)
            raise
        if old_id is not None and old_id != asset.id:
            await self.media.delete(old_id)
        return await self.to_response(row)

    async def delete_image(self) -> None:
        row = await self._get_row()
        if row is None:
            raise NotFoundError("Profile not found")
        old_id = row.profile_image_media_id
        row.profile_image_media_id = None
        await self.pg_session.commit()
        if old_id is not None:
            await self.media.delete(old_id)

    async def upload_resume(self, file: UploadFile) -> ProfileResponse:
        row = await self._get_row()
        if row is None:
            raise NotFoundError("Profile not found")
        old_id = row.resume_media_id
        asset = await self.media.store(file, MediaKind.RESUME)
        row.resume_media_id = asset.id
        try:
            await self.pg_session.commit()
            await self.pg_session.refresh(row)
        except Exception:
            await self.pg_session.rollback()
            if asset.id != old_id:
                await self.media.delete(asset.id)
            raise
        if old_id is not None and old_id != asset.id:
            await self.media.delete(old_id)
        return await self.to_response(row)

    async def delete_resume(self) -> None:
        row = await self._get_row()
        if row is None:
            raise NotFoundError("Profile not found")
        old_id = row.resume_media_id
        row.resume_media_id = None
        await self.pg_session.commit()
        if old_id is not None:
            await self.media.delete(old_id)
