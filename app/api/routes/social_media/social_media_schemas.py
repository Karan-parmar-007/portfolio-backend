from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.constants import SOCIAL_PLATFORMS

SocialPlatform = Literal[
    "github",
    "linkedin",
    "instagram",
    "twitter",
    "x",
    "youtube",
    "codepen",
    "stackoverflow",
    "medium",
    "dribbble",
    "email",
]


class SocialMediaResponse(BaseModel):
    id: UUID
    platform: str
    label: str
    url: str
    sequence: int
    show_in_rail: bool


class SocialMediaCreateRequest(BaseModel):
    platform: SocialPlatform
    label: str = Field(..., max_length=50)
    url: str = Field(..., max_length=500)
    sequence: int | None = None
    show_in_rail: bool = True

    @field_validator("platform")
    @classmethod
    def known_platform(cls, value: str) -> str:
        if value not in SOCIAL_PLATFORMS:
            raise ValueError(f"Unknown platform: {value}")
        return value

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        if value.startswith("mailto:"):
            return value
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("url must be http(s) or mailto:")
        return value


class SocialMediaUpdateRequest(BaseModel):
    platform: SocialPlatform | None = None
    label: str | None = Field(default=None, max_length=50)
    url: str | None = Field(default=None, max_length=500)
    sequence: int | None = None
    show_in_rail: bool | None = None

    @field_validator("platform")
    @classmethod
    def known_platform(cls, value: str | None) -> str | None:
        if value is not None and value not in SOCIAL_PLATFORMS:
            raise ValueError(f"Unknown platform: {value}")
        return value

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.startswith("mailto:"):
            return value
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("url must be http(s) or mailto:")
        return value


class SocialMediaListResponse(BaseModel):
    items: list[SocialMediaResponse]
