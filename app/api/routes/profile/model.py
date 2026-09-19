from datetime import datetime
from typing import ClassVar, Optional
from uuid import UUID

import uuid6
from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlmodel import Field, SQLModel, func


class ProfileInfo(SQLModel, table=True):
    __tablename__: ClassVar[str] = "profile_info"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    name: str = Field(sa_column=Column(String(100), nullable=False))
    headline: Optional[str] = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )
    hero_greeting: Optional[str] = Field(
        default="Hi, my name is",
        sa_column=Column(String(100), nullable=True),
    )
    about: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    email: str = Field(
        sa_column=Column(String(255), unique=True, nullable=False)
    )
    phone: Optional[str] = Field(
        default=None, sa_column=Column(String(30), nullable=True)
    )
    location: Optional[str] = Field(
        default=None, sa_column=Column(String(100), nullable=True)
    )
    available_for_work: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
    )
    resume_media_id: Optional[UUID] = Field(
        default=None,
        foreign_key="media_assets.id",
        ondelete="SET NULL",
    )
    profile_image_media_id: Optional[UUID] = Field(
        default=None,
        foreign_key="media_assets.id",
        ondelete="SET NULL",
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )
