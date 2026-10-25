from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.api.routes.media.media_schemas import MediaRef


class ProfileResponse(BaseModel):
    name: str
    headline: str | None = None
    hero_greeting: str | None = None
    about: str | None = None
    email: EmailStr
    phone: str | None = None
    location: str | None = None
    available_for_work: bool = True
    profile_image: MediaRef | None = None
    resume: MediaRef | None = None


class ProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    headline: str | None = Field(default=None, max_length=255)
    hero_greeting: str | None = Field(default=None, max_length=100)
    about: str | None = None
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=100)
    available_for_work: bool | None = None
