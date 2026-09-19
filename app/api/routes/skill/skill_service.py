from __future__ import annotations

import logging
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.routes.media.media_schemas import media_asset_to_ref
from app.api.routes.media.media_service import MediaService
from app.api.routes.media.model import MediaAsset
from app.api.routes.skill.model import Skill, SkillCategory
from app.api.routes.skill.skill_schemas import (
    SkillCategoryCreateRequest,
    SkillCategoryResponse,
    SkillCategoryUpdateRequest,
    SkillResponse,
)
from app.core.constants import MediaKind
from app.core.errors import ConflictError, NotFoundError, ValidationError

logger = logging.getLogger(__name__)

HOME_CATEGORY_LIMIT = 3


class SkillService:
    def __init__(self, pg_session: AsyncSession, garage_client: object) -> None:
        self.pg_session = pg_session
        self.media = MediaService(pg_session=pg_session, garage_client=garage_client)

    async def _icon_ref(self, media_id: UUID | None):
        if media_id is None:
            return None
        asset = (
            await self.pg_session.execute(
                select(MediaAsset).where(MediaAsset.id == media_id)
            )
        ).scalar_one_or_none()
        return media_asset_to_ref(asset)

    async def skill_to_response(self, skill: Skill) -> SkillResponse:
        category_name = skill.category.name if skill.category else None
        return SkillResponse(
            id=skill.id,
            name=skill.name,
            sequence=skill.sequence,
            category_id=skill.category_id,
            category_name=category_name,
            show_in_about=skill.show_in_about,
            icon=await self._icon_ref(skill.icon_media_id),
        )

    async def _category_to_response(self, cat: SkillCategory) -> SkillCategoryResponse:
        skills_sorted = sorted(cat.skills, key=lambda s: s.sequence)
        return SkillCategoryResponse(
            id=cat.id,
            name=cat.name,
            sequence=cat.sequence,
            show_on_home=cat.show_on_home,
            skills=[await self.skill_to_response(s) for s in skills_sorted],
        )

    async def _assert_home_capacity(self, *, exclude_id: UUID | None = None) -> None:
        stmt = select(func.count()).select_from(SkillCategory).where(
            SkillCategory.show_on_home.is_(True)
        )
        if exclude_id is not None:
            stmt = stmt.where(SkillCategory.id != exclude_id)
        count = (await self.pg_session.execute(stmt)).scalar_one()
        if count >= HOME_CATEGORY_LIMIT:
            raise ValidationError(
                f"At most {HOME_CATEGORY_LIMIT} skill categories can appear on the home page"
            )

    async def list_categories(
        self, *, on_home: bool | None = None
    ) -> list[SkillCategoryResponse]:
        stmt = (
            select(SkillCategory)
            .options(selectinload(SkillCategory.skills).selectinload(Skill.category))
            .order_by(SkillCategory.sequence.asc())
        )
        if on_home is True:
            stmt = stmt.where(SkillCategory.show_on_home.is_(True))
        rows = (await self.pg_session.execute(stmt)).scalars().all()
        result: list[SkillCategoryResponse] = []
        for cat in rows:
            result.append(await self._category_to_response(cat))
        if on_home is True:
            return result[:HOME_CATEGORY_LIMIT]
        return result

    async def list_skills(
        self,
        *,
        category_id: UUID | None = None,
        in_about: bool | None = None,
    ) -> list[SkillResponse]:
        stmt = (
            select(Skill)
            .options(selectinload(Skill.category))
            .order_by(Skill.sequence.asc())
        )
        if category_id is not None:
            stmt = stmt.where(Skill.category_id == category_id)
        if in_about is True:
            stmt = stmt.where(Skill.show_in_about.is_(True))
        rows = (await self.pg_session.execute(stmt)).scalars().all()
        return [await self.skill_to_response(s) for s in rows]

    async def create_category(
        self, data: SkillCategoryCreateRequest
    ) -> SkillCategoryResponse:
        existing = (
            await self.pg_session.execute(
                select(SkillCategory).where(SkillCategory.name == data.name)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("Skill category name already exists")
        sequence = data.sequence
        if sequence is None:
            max_seq = (
                await self.pg_session.execute(
                    select(func.max(SkillCategory.sequence))
                )
            ).scalar_one_or_none()
            sequence = (max_seq or 0) + 1
        if data.show_on_home:
            await self._assert_home_capacity()
        row = SkillCategory(
            name=data.name,
            sequence=sequence,
            show_on_home=data.show_on_home,
        )
        self.pg_session.add(row)
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return SkillCategoryResponse(
            id=row.id,
            name=row.name,
            sequence=row.sequence,
            show_on_home=row.show_on_home,
            skills=[],
        )

    async def update_category(
        self, category_id: UUID, data: SkillCategoryUpdateRequest
    ) -> SkillCategoryResponse:
        row = (
            await self.pg_session.execute(
                select(SkillCategory)
                .options(selectinload(SkillCategory.skills).selectinload(Skill.category))
                .where(SkillCategory.id == category_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Skill category not found")
        payload = data.model_dump(exclude_unset=True)
        if "name" in payload:
            clash = (
                await self.pg_session.execute(
                    select(SkillCategory).where(
                        SkillCategory.name == payload["name"],
                        SkillCategory.id != category_id,
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise ConflictError("Skill category name already exists")
        if payload.get("show_on_home") is True and not row.show_on_home:
            await self._assert_home_capacity(exclude_id=category_id)
        for key, value in payload.items():
            setattr(row, key, value)
        await self.pg_session.commit()
        await self.pg_session.refresh(row)
        return await self._category_to_response(row)

    async def delete_category(self, category_id: UUID) -> None:
        row = (
            await self.pg_session.execute(
                select(SkillCategory).where(SkillCategory.id == category_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Skill category not found")
        await self.pg_session.delete(row)
        await self.pg_session.commit()

    async def reorder_categories(
        self, ids: list[UUID]
    ) -> list[SkillCategoryResponse]:
        rows = (
            await self.pg_session.execute(select(SkillCategory))
        ).scalars().all()
        by_id = {r.id: r for r in rows}
        if set(ids) != set(by_id):
            raise ValidationError("Reorder must include every existing id exactly once")
        for index, item_id in enumerate(ids):
            by_id[item_id].sequence = index + 1
        await self.pg_session.commit()
        return await self.list_categories()

    async def create_skill(
        self,
        *,
        name: str,
        category_id: UUID | None,
        sequence: int | None,
        show_in_about: bool,
        icon: UploadFile | None,
    ) -> SkillResponse:
        existing = (
            await self.pg_session.execute(select(Skill).where(Skill.name == name))
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError("Skill name already exists")
        if category_id is not None:
            cat = (
                await self.pg_session.execute(
                    select(SkillCategory).where(SkillCategory.id == category_id)
                )
            ).scalar_one_or_none()
            if cat is None:
                raise NotFoundError("Skill category not found")
        seq = sequence
        if seq is None:
            max_seq = (
                await self.pg_session.execute(select(func.max(Skill.sequence)))
            ).scalar_one_or_none()
            seq = (max_seq or 0) + 1

        icon_id = None
        asset = None
        if icon is not None and icon.filename:
            asset = await self.media.store(icon, MediaKind.SKILL_ICON)
            icon_id = asset.id

        row = Skill(
            name=name,
            category_id=category_id,
            sequence=seq,
            show_in_about=show_in_about,
            icon_media_id=icon_id,
        )
        self.pg_session.add(row)
        try:
            await self.pg_session.commit()
            await self.pg_session.refresh(row)
        except Exception:
            await self.pg_session.rollback()
            if asset is not None:
                await self.media.delete(asset.id)
            raise

        loaded = (
            await self.pg_session.execute(
                select(Skill)
                .options(selectinload(Skill.category))
                .where(Skill.id == row.id)
            )
        ).scalar_one()
        return await self.skill_to_response(loaded)

    async def update_skill(
        self,
        skill_id: UUID,
        *,
        name: str | None,
        category_id: UUID | None,
        sequence: int | None,
        show_in_about: bool | None,
        icon: UploadFile | None,
        category_id_set: bool = False,
    ) -> SkillResponse:
        row = (
            await self.pg_session.execute(
                select(Skill)
                .options(selectinload(Skill.category))
                .where(Skill.id == skill_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Skill not found")
        if name is not None:
            clash = (
                await self.pg_session.execute(
                    select(Skill).where(Skill.name == name, Skill.id != skill_id)
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise ConflictError("Skill name already exists")
            row.name = name
        if category_id_set:
            if category_id is not None:
                cat = (
                    await self.pg_session.execute(
                        select(SkillCategory).where(SkillCategory.id == category_id)
                    )
                ).scalar_one_or_none()
                if cat is None:
                    raise NotFoundError("Skill category not found")
            row.category_id = category_id
        if sequence is not None:
            row.sequence = sequence
        if show_in_about is not None:
            row.show_in_about = show_in_about

        old_icon = row.icon_media_id
        new_asset = None
        if icon is not None and icon.filename:
            new_asset = await self.media.store(icon, MediaKind.SKILL_ICON)
            row.icon_media_id = new_asset.id

        try:
            await self.pg_session.commit()
            await self.pg_session.refresh(row)
        except Exception:
            await self.pg_session.rollback()
            if new_asset is not None:
                await self.media.delete(new_asset.id)
            raise

        if new_asset is not None and old_icon is not None and old_icon != new_asset.id:
            await self.media.delete(old_icon)

        loaded = (
            await self.pg_session.execute(
                select(Skill)
                .options(selectinload(Skill.category))
                .where(Skill.id == skill_id)
            )
        ).scalar_one()
        return await self.skill_to_response(loaded)

    async def delete_skill(self, skill_id: UUID) -> None:
        row = (
            await self.pg_session.execute(select(Skill).where(Skill.id == skill_id))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Skill not found")
        icon_id = row.icon_media_id
        await self.pg_session.delete(row)
        await self.pg_session.commit()
        if icon_id is not None:
            await self.media.delete(icon_id)

    async def delete_skill_icon(self, skill_id: UUID) -> None:
        row = (
            await self.pg_session.execute(select(Skill).where(Skill.id == skill_id))
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Skill not found")
        old_id = row.icon_media_id
        row.icon_media_id = None
        await self.pg_session.commit()
        if old_id is not None:
            await self.media.delete(old_id)

    async def reorder_skills(self, ids: list[UUID]) -> list[SkillResponse]:
        rows = (await self.pg_session.execute(select(Skill))).scalars().all()
        by_id = {r.id: r for r in rows}
        if set(ids) != set(by_id):
            raise ValidationError("Reorder must include every existing id exactly once")
        for index, item_id in enumerate(ids):
            by_id[item_id].sequence = index + 1
        await self.pg_session.commit()
        return await self.list_skills()
