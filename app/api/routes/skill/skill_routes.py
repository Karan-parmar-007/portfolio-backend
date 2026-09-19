from uuid import UUID

from fastapi import APIRouter, Query

from app.api.dependencies import SkillServiceDep
from app.api.routes.skill.skill_schemas import (
    SkillCategoryListResponse,
    SkillListResponse,
)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/skill-categories", response_model=SkillCategoryListResponse)
async def list_skill_categories(
    service: SkillServiceDep,
) -> SkillCategoryListResponse:
    return SkillCategoryListResponse(items=await service.list_categories())


@router.get("/skills", response_model=SkillListResponse)
async def list_skills(
    service: SkillServiceDep,
    category_id: UUID | None = Query(default=None),
    in_about: bool | None = Query(default=None),
) -> SkillListResponse:
    return SkillListResponse(
        items=await service.list_skills(category_id=category_id, in_about=in_about)
    )
