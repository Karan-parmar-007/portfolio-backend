from datetime import datetime
from typing import ClassVar, Optional
from uuid import UUID

import uuid6
from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlmodel import Field, SQLModel, func


class ContactMessage(SQLModel, table=True):
    __tablename__: ClassVar[str] = "contact_messages"

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    name: str = Field(sa_column=Column(String(100), nullable=False))
    email: str = Field(sa_column=Column(String(255), nullable=False))
    phone: Optional[str] = Field(
        default=None, sa_column=Column(String(30), nullable=True)
    )
    subject: str = Field(sa_column=Column(String(200), nullable=False))
    message: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )
    is_read: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false"),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
    )
