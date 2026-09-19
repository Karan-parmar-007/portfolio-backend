from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.api.routes.media.media_schemas import MediaRef


class SkillResponse(BaseModel):
    id: UUID
    name: str
    sequence: int
    category_id: UUID | None = None
    category_name: str | None = None
    show_in_about: bool = False
    icon: MediaRef | None = None


class SkillCategoryResponse(BaseModel):
    id: UUID
    name: str
    sequence: int
    show_on_home: bool = False
    skills: list[SkillResponse] = Field(default_factory=list)


class SkillCategoryCreateRequest(BaseModel):
    name: str = Field(..., max_length=100)
    sequence: int | None = None
    show_on_home: bool = False


class SkillCategoryUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    sequence: int | None = None
    show_on_home: bool | None = None


class SkillCategoryListResponse(BaseModel):
    items: list[SkillCategoryResponse]


class SkillListResponse(BaseModel):
    items: list[SkillResponse]
