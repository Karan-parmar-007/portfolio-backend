from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.portfolio.education.education_schemas import (
    EducationCreateRequest,
    EducationResponse,
    EducationUpdateRequest,
)
from app.api.routes.portfolio.education.model import Education
from app.core.errors import NotFoundError, ValidationError


def _to_response(row: Education) -> EducationResponse:
    return EducationResponse.model_validate(row, from_attributes=True)


class EducationService:
    def __init__(self, pg_session: AsyncSession) -> None:
        self.pg_session = pg_session

    async def list_all(self) -> list[EducationResponse]:
        rows = (
            await self.pg_session.execute(
                select(Education).order_by(Education.sequence.asc())
            )
        ).scalars().all()
        return [_to_response(r) for r in rows]

    async def create(self, data: EducationCreateRequest) -> EducationResponse:
        sequence = data.sequence
        if sequence is None:
            max_seq = (
                await self.pg_session.execute(select(func.max(Education.sequence)))
            ).scalar_one_or_none()
            sequence = (max_seq or 0) + 1
        row = Education(
            sequence=sequence,
            school=data.school,
            degree=data.degree,
            field_of_study=data.field_of_study,
            start_year=data.start_year,
            end_year=data.end_year,
            score=data.score,
            score_label=data.score_label,
            description=data.description,
        )
        self.pg_session.add(row)
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return _to_response(row)

    async def update(
        self, education_id: UUID, data: EducationUpdateRequest
    ) -> EducationResponse:
        row = (
            await self.pg_session.execute(
                select(Education).where(Education.id == education_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Education not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        if row.end_year is not None and row.end_year < row.start_year:
            raise ValidationError("end_year must be >= start_year")
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return _to_response(row)

    async def delete(self, education_id: UUID) -> None:
        row = (
            await self.pg_session.execute(
                select(Education).where(Education.id == education_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Education not found")
        await self.pg_session.delete(row)
        await self.pg_session.commit()

    async def reorder(self, ids: list[UUID]) -> list[EducationResponse]:
        rows = (
            await self.pg_session.execute(select(Education))
        ).scalars().all()
        by_id = {r.id: r for r in rows}
        if set(ids) != set(by_id):
            raise ValidationError("Reorder must include every existing id exactly once")
        for index, item_id in enumerate(ids):
            by_id[item_id].sequence = index + 1
        await self.pg_session.commit()
        return await self.list_all()
