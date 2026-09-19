from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.contact_message.contact_schemas import (
    ContactMessageCreateRequest,
    ContactMessageResponse,
    ContactMessageUpdateRequest,
)
from app.api.routes.contact_message.model import ContactMessage
from app.api.schemas.pagination import PaginationParams
from app.core.errors import NotFoundError


def _to_response(row: ContactMessage) -> ContactMessageResponse:
    return ContactMessageResponse.model_validate(row, from_attributes=True)


class ContactMessageService:
    def __init__(self, pg_session: AsyncSession) -> None:
        self.pg_session = pg_session

    async def create(
        self, data: ContactMessageCreateRequest
    ) -> ContactMessageResponse:
        phone = data.phone.strip() if data.phone else None
        row = ContactMessage(
            name=data.name.strip(),
            email=str(data.email).strip(),
            phone=phone or None,
            subject=data.subject.strip(),
            message=(data.message or "").strip(),
        )
        self.pg_session.add(row)
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return _to_response(row)

    async def list_admin(
        self, pagination: PaginationParams
    ) -> tuple[list[ContactMessageResponse], int]:
        count_stmt = select(func.count()).select_from(ContactMessage)
        total = (await self.pg_session.execute(count_stmt)).scalar_one()
        stmt = (
            select(ContactMessage)
            .order_by(ContactMessage.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.page_size)
        )
        rows = (await self.pg_session.execute(stmt)).scalars().all()
        return [_to_response(r) for r in rows], total

    async def get(self, message_id: UUID) -> ContactMessageResponse:
        row = (
            await self.pg_session.execute(
                select(ContactMessage).where(ContactMessage.id == message_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Contact message not found")
        return _to_response(row)

    async def update(
        self, message_id: UUID, data: ContactMessageUpdateRequest
    ) -> ContactMessageResponse:
        row = (
            await self.pg_session.execute(
                select(ContactMessage).where(ContactMessage.id == message_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Contact message not found")
        row.is_read = data.is_read
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return _to_response(row)

    async def delete(self, message_id: UUID) -> None:
        row = (
            await self.pg_session.execute(
                select(ContactMessage).where(ContactMessage.id == message_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Contact message not found")
        await self.pg_session.delete(row)
        await self.pg_session.commit()
