from datetime import datetime
from typing import ClassVar
from uuid import UUID

import uuid6
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlmodel import Field, SQLModel, func


class SocialMediaLink(SQLModel, table=True):
    __tablename__: ClassVar[str] = "social_media_links"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    platform: str = Field(sa_column=Column(String(30), nullable=False))
    label: str = Field(sa_column=Column(String(50), nullable=False))
    url: str = Field(sa_column=Column(String(500), nullable=False))
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    show_in_rail: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default="true"),
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
