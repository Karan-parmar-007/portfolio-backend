from datetime import datetime
from typing import Optional
from typing import ClassVar
from uuid import UUID

import uuid6
from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlmodel import Field, Relationship, SQLModel, func


class SkillCategory(SQLModel, table=True):
    __tablename__: ClassVar[str] = "skill_categories"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    name: str = Field(sa_column=Column(String(100), unique=True, nullable=False))
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    show_on_home: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
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

    skills: list["Skill"] = Relationship(back_populates="category")


class Skill(SQLModel, table=True):
    __tablename__: ClassVar[str] = "skills"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    name: str = Field(sa_column=Column(String(100), unique=True, nullable=False))
    category_id: Optional[UUID] = Field(
        default=None,
        foreign_key="skill_categories.id",
        ondelete="SET NULL",
    )
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    icon_media_id: Optional[UUID] = Field(
        default=None,
        foreign_key="media_assets.id",
        ondelete="SET NULL",
    )
    show_in_about: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
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

    category: Optional[SkillCategory] = Relationship(back_populates="skills")
