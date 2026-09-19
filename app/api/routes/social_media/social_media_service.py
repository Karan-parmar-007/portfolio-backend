from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.social_media.model import SocialMediaLink
from app.api.routes.social_media.social_media_schemas import (
    SocialMediaCreateRequest,
    SocialMediaResponse,
    SocialMediaUpdateRequest,
)
from app.core.errors import NotFoundError, ValidationError


def _to_response(row: SocialMediaLink) -> SocialMediaResponse:
    return SocialMediaResponse.model_validate(row, from_attributes=True)


class SocialMediaService:
    def __init__(self, pg_session: AsyncSession) -> None:
        self.pg_session = pg_session

    async def list_all(
        self, *, in_rail: bool | None = None
    ) -> list[SocialMediaResponse]:
        stmt = select(SocialMediaLink).order_by(SocialMediaLink.sequence.asc())
        if in_rail is True:
            stmt = stmt.where(SocialMediaLink.show_in_rail.is_(True))
        rows = (await self.pg_session.execute(stmt)).scalars().all()
        return [_to_response(r) for r in rows]

    async def create(self, data: SocialMediaCreateRequest) -> SocialMediaResponse:
        sequence = data.sequence
        if sequence is None:
            max_seq = (
                await self.pg_session.execute(
                    select(func.max(SocialMediaLink.sequence))
                )
            ).scalar_one_or_none()
            sequence = (max_seq or 0) + 1
        row = SocialMediaLink(
            platform=data.platform,
            label=data.label,
            url=data.url,
            sequence=sequence,
            show_in_rail=data.show_in_rail,
        )
        self.pg_session.add(row)
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return _to_response(row)

    async def update(
        self, link_id: UUID, data: SocialMediaUpdateRequest
    ) -> SocialMediaResponse:
        row = (
            await self.pg_session.execute(
                select(SocialMediaLink).where(SocialMediaLink.id == link_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Social media link not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return _to_response(row)

    async def delete(self, link_id: UUID) -> None:
        row = (
            await self.pg_session.execute(
                select(SocialMediaLink).where(SocialMediaLink.id == link_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Social media link not found")
        await self.pg_session.delete(row)
        await self.pg_session.commit()

    async def reorder(self, ids: list[UUID]) -> list[SocialMediaResponse]:
        rows = (
            await self.pg_session.execute(select(SocialMediaLink))
        ).scalars().all()
        by_id = {r.id: r for r in rows}
        if set(ids) != set(by_id):
            raise ValidationError("Reorder must include every existing id exactly once")
        for index, item_id in enumerate(ids):
            by_id[item_id].sequence = index + 1
        await self.pg_session.commit()
        return await self.list_all()
