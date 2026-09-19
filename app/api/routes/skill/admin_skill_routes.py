from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status

from app.api.all_dependencies.owner_required import require_owner
from app.api.dependencies import SkillServiceDep
from app.api.routes.skill.skill_schemas import (
    SkillCategoryCreateRequest,
    SkillCategoryListResponse,
    SkillCategoryResponse,
    SkillCategoryUpdateRequest,
    SkillListResponse,
    SkillResponse,
)
from app.api.schemas.common import ReorderRequest

router = APIRouter(
    prefix="/admin",
    tags=["admin:skills"],
    dependencies=[Depends(require_owner)],
)


@router.get("/skill-categories", response_model=SkillCategoryListResponse)
async def admin_list_categories(
    service: SkillServiceDep,
) -> SkillCategoryListResponse:
    return SkillCategoryListResponse(items=await service.list_categories())


@router.post(
    "/skill-categories",
    response_model=SkillCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_category(
    body: SkillCategoryCreateRequest,
    service: SkillServiceDep,
) -> SkillCategoryResponse:
    return await service.create_category(body)


@router.put("/skill-categories/{category_id}", response_model=SkillCategoryResponse)
async def update_category(
    category_id: UUID,
    body: SkillCategoryUpdateRequest,
    service: SkillServiceDep,
) -> SkillCategoryResponse:
    return await service.update_category(category_id, body)


@router.delete("/skill-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(
    category_id: UUID,
    service: SkillServiceDep,
) -> None:
    await service.delete_category(category_id)


@router.patch("/skill-categories/reorder", response_model=SkillCategoryListResponse)
async def reorder_categories(
    body: ReorderRequest,
    service: SkillServiceDep,
) -> SkillCategoryListResponse:
    return SkillCategoryListResponse(items=await service.reorder_categories(body.ids))


@router.get("/skills", response_model=SkillListResponse)
async def admin_list_skills(service: SkillServiceDep) -> SkillListResponse:
    return SkillListResponse(items=await service.list_skills())


@router.post("/skills", response_model=SkillResponse, status_code=status.HTTP_201_CREATED)
async def create_skill(
    service: SkillServiceDep,
    name: str = Form(...),
    category_id: UUID | None = Form(default=None),
    sequence: int | None = Form(default=None),
    show_in_about: bool = Form(default=False),
    icon: UploadFile | None = File(default=None),
) -> SkillResponse:
    return await service.create_skill(
        name=name,
        category_id=category_id,
        sequence=sequence,
        show_in_about=show_in_about,
        icon=icon,
    )


@router.put("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(
    skill_id: UUID,
    request: Request,
    service: SkillServiceDep,
    name: str | None = Form(default=None),
    category_id: UUID | None = Form(default=None),
    sequence: int | None = Form(default=None),
    show_in_about: bool | None = Form(default=None),
    icon: UploadFile | None = File(default=None),
) -> SkillResponse:
    form = await request.form()
    return await service.update_skill(
        skill_id,
        name=name,
        category_id=category_id,
        sequence=sequence,
        show_in_about=show_in_about,
        icon=icon,
        category_id_set="category_id" in form,
    )


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: UUID, service: SkillServiceDep) -> None:
    await service.delete_skill(skill_id)


@router.delete("/skills/{skill_id}/icon", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill_icon(skill_id: UUID, service: SkillServiceDep) -> None:
    await service.delete_skill_icon(skill_id)


@router.patch("/skills/reorder", response_model=SkillListResponse)
async def reorder_skills(
    body: ReorderRequest,
    service: SkillServiceDep,
) -> SkillListResponse:
    return SkillListResponse(items=await service.reorder_skills(body.ids))
