from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Optional
from uuid import UUID

import uuid6
from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text
from sqlmodel import Field, SQLModel, func


class Education(SQLModel, table=True):
    __tablename__: ClassVar[str] = "education"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    sequence: int = Field(sa_column=Column(Integer, nullable=False))
    school: str = Field(sa_column=Column(String(150), nullable=False))
    degree: str = Field(sa_column=Column(String(150), nullable=False))
    field_of_study: Optional[str] = Field(
        default=None, sa_column=Column(String(150), nullable=True)
    )
    start_year: int = Field(sa_column=Column(Integer, nullable=False))
    end_year: Optional[int] = Field(
        default=None, sa_column=Column(Integer, nullable=True)
    )
    score: Optional[Decimal] = Field(
        default=None, sa_column=Column(Numeric(5, 2), nullable=True)
    )
    score_label: Optional[str] = Field(
        default=None, sa_column=Column(String(20), nullable=True)
    )
    description: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
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
