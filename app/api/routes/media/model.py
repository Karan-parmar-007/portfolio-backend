from datetime import datetime
from typing import ClassVar, Optional
from uuid import UUID

import uuid6
from sqlalchemy import BigInteger, Column, DateTime, Index, String
from sqlmodel import Field, SQLModel, func

from app.core.constants import MediaKind


class MediaAsset(SQLModel, table=True):
    __tablename__: ClassVar[str] = "media_assets"
    __table_args__ = (
        Index("ix_media_assets_checksum_sha256", "checksum_sha256"),
        Index("ix_media_assets_kind", "kind"),
    )

    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    object_key: str = Field(
        sa_column=Column(String(512), unique=True, nullable=False)
    )
    filename: str = Field(sa_column=Column(String(255), nullable=False))
    content_type: str = Field(sa_column=Column(String(128), nullable=False))
    size_bytes: int = Field(sa_column=Column(BigInteger, nullable=False))
    kind: MediaKind = Field(sa_column=Column(String(32), nullable=False))
    checksum_sha256: str = Field(sa_column=Column(String(64), nullable=False))
    width: Optional[int] = Field(default=None)
    height: Optional[int] = Field(default=None)
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
