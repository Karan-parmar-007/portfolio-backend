from datetime import date, datetime
from typing import Any, ClassVar, Optional
from uuid import UUID

import uuid6
from sqlalchemy import JSON, Column, Date, DateTime, Integer, String
from sqlmodel import Field, SQLModel, func


class WorkExperience(SQLModel, table=True):
    __tablename__: ClassVar[str] = "work_experiences"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    company: str = Field(sa_column=Column(String(150), nullable=False))
    company_url: Optional[str] = Field(
        default=None, sa_column=Column(String(500), nullable=True)
    )
    position: str = Field(sa_column=Column(String(150), nullable=False))
    location: Optional[str] = Field(
        default=None, sa_column=Column(String(150), nullable=True)
    )
    employment_type: Optional[str] = Field(
        default=None, sa_column=Column(String(50), nullable=True)
    )
    description: list[Any] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    start_date: date = Field(sa_column=Column(Date, nullable=False))
    end_date: Optional[date] = Field(
        default=None, sa_column=Column(Date, nullable=True)
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
