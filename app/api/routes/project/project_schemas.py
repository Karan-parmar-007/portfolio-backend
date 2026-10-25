from __future__ import annotations

from datetime import datetime
from typing import Annotated
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AfterValidator, BaseModel, BeforeValidator, Field

from app.api.routes.media.media_schemas import MediaRef
from app.api.routes.project.project_constants import (
    MAX_LABEL_LENGTH,
    MAX_TAGS_PER_PROJECT,
    MAX_TECH_STACK_ITEMS,
    MAX_URL_LENGTH,
    ProjectStatus,
)
from app.api.schemas.pagination import PaginatedResponse


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


def optional_url(value: object) -> object:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    if len(text) > MAX_URL_LENGTH:
        raise ValueError(f"URL must be at most {MAX_URL_LENGTH} characters")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("URL must start with http:// or https://")
    return text


def _labels(limit: int):
    def clean(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for raw in values:
            label = raw.strip()
            if not label:
                continue
            if len(label) > MAX_LABEL_LENGTH:
                raise ValueError(f"'{label[:20]}…' is longer than {MAX_LABEL_LENGTH} characters")
            key = label.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(label)
        if len(result) > limit:
            raise ValueError(f"At most {limit} items allowed")
        return result

    return clean


Name = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=150)]
ShortText = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=500)]
OptionalUrl = Annotated[str | None, BeforeValidator(optional_url)]
TechStack = Annotated[list[str], AfterValidator(_labels(MAX_TECH_STACK_ITEMS))]
Tags = Annotated[list[str], AfterValidator(_labels(MAX_TAGS_PER_PROJECT))]
LongText = Annotated[str, Field(max_length=200_000)]


class ProjectSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    short_description: str
    status: ProjectStatus
    is_featured: bool
    sequence: int
    github_url: str | None = None
    try_url: str | None = None
    cover: MediaRef | None = None
    tech_stack: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class ProjectDetail(ProjectSummary):
    long_description: str
    created_at: datetime
    updated_at: datetime


class ProjectPage(PaginatedResponse[ProjectSummary]):
    pass


class ProjectListResponse(BaseModel):
    items: list[ProjectSummary]


class FacetCount(BaseModel):
    value: str
    count: int


class ProjectFacetsResponse(BaseModel):
    total: int
    statuses: list[FacetCount]
    skills: list[FacetCount]
    tags: list[FacetCount]


class ProjectCreateRequest(BaseModel):
    name: Name
    short_description: ShortText
    long_description: LongText = ""
    status: ProjectStatus = ProjectStatus.OFFLINE
    is_featured: bool = False
    github_url: OptionalUrl = None
    try_url: OptionalUrl = None
    tech_stack: TechStack = Field(default_factory=list)
    tags: Tags = Field(default_factory=list)


class ProjectUpdateRequest(BaseModel):
    name: Name | None = None
    short_description: ShortText | None = None
    long_description: LongText | None = None
    status: ProjectStatus | None = None
    is_featured: bool | None = None
    github_url: OptionalUrl = None
    try_url: OptionalUrl = None
    tech_stack: TechStack | None = None
    tags: Tags | None = None


class ProjectFeaturedRequest(BaseModel):
    is_featured: bool


class ProjectStatusRequest(BaseModel):
    status: ProjectStatus


class ProjectTagCreateRequest(BaseModel):
    name: Annotated[
        str, BeforeValidator(_strip), Field(min_length=1, max_length=MAX_LABEL_LENGTH)
    ]


class ProjectTagResponse(BaseModel):
    id: UUID
    name: str
    project_count: int = 0


class ProjectTagListResponse(BaseModel):
    items: list[ProjectTagResponse]
