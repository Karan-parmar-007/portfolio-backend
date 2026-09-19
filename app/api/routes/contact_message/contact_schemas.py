from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class ContactMessageCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    subject: str = Field(..., min_length=1, max_length=200)
    message: str = Field(default="", max_length=5000)


class ContactMessageResponse(BaseModel):
    id: UUID
    name: str
    email: EmailStr
    phone: str | None = None
    subject: str
    message: str
    is_read: bool
    created_at: datetime


class ContactMessageUpdateRequest(BaseModel):
    is_read: bool


class ContactSubmitResponse(BaseModel):
    message: str
