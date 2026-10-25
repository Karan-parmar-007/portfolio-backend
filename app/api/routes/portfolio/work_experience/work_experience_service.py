from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.portfolio.work_experience.model import WorkExperience
from app.api.routes.portfolio.work_experience.work_experience_schemas import (
    WorkExperienceCreateRequest,
    WorkExperienceResponse,
    WorkExperienceUpdateRequest,
)
from app.core.errors import NotFoundError, ValidationError


def _to_response(row: WorkExperience) -> WorkExperienceResponse:
    description = row.description if isinstance(row.description, list) else []
    return WorkExperienceResponse(
        id=row.id,
        sequence=row.sequence,
        company=row.company,
        company_url=row.company_url,
        position=row.position,
        location=row.location,
        employment_type=row.employment_type,
        description=[str(x) for x in description],
        start_date=row.start_date,
        end_date=row.end_date,
        is_current=row.end_date is None,
    )


class WorkExperienceService:
    def __init__(self, pg_session: AsyncSession) -> None:
        self.pg_session = pg_session

    async def list_all(self) -> list[WorkExperienceResponse]:
        rows = (
            await self.pg_session.execute(
                select(WorkExperience).order_by(WorkExperience.sequence.asc())
            )
        ).scalars().all()
        return [_to_response(r) for r in rows]

    async def create(
        self, data: WorkExperienceCreateRequest
    ) -> WorkExperienceResponse:
        sequence = data.sequence
        if sequence is None:
            max_seq = (
                await self.pg_session.execute(
                    select(func.max(WorkExperience.sequence))
                )
            ).scalar_one_or_none()
            sequence = (max_seq or 0) + 1
        row = WorkExperience(
            sequence=sequence,
            company=data.company,
            company_url=data.company_url,
            position=data.position,
            location=data.location,
            employment_type=data.employment_type,
            description=data.description,
            start_date=data.start_date,
            end_date=data.end_date,
        )
        self.pg_session.add(row)
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return _to_response(row)

    async def update(
        self, experience_id: UUID, data: WorkExperienceUpdateRequest
    ) -> WorkExperienceResponse:
        row = (
            await self.pg_session.execute(
                select(WorkExperience).where(WorkExperience.id == experience_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Work experience not found")
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(row, key, value)
        if row.end_date is not None and row.end_date < row.start_date:
            raise ValidationError("end_date must be >= start_date")
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return _to_response(row)

    async def delete(self, experience_id: UUID) -> None:
        row = (
            await self.pg_session.execute(
                select(WorkExperience).where(WorkExperience.id == experience_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Work experience not found")
        await self.pg_session.delete(row)
        await self.pg_session.commit()

    async def reorder(self, ids: list[UUID]) -> list[WorkExperienceResponse]:
        rows = (
            await self.pg_session.execute(select(WorkExperience))
        ).scalars().all()
        by_id = {r.id: r for r in rows}
        if set(ids) != set(by_id):
            raise ValidationError("Reorder must include every existing id exactly once")
        for index, item_id in enumerate(ids):
            by_id[item_id].sequence = index + 1
        await self.pg_session.commit()
        return await self.list_all()
