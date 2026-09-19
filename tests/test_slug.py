"""Unit tests for unique_slug generation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
import uuid6
from sqlmodel import Field, SQLModel, Column, String

from app.core.slug import unique_slug


class DummyModel(SQLModel, table=True):
    __tablename__ = "dummy_slug_table"
    id: UUID = Field(default_factory=uuid6.uuid7, primary_key=True)
    slug: str = Field(sa_column=Column(String, unique=True))


@pytest.mark.asyncio
async def test_unique_slug_no_collision() -> None:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    value = await unique_slug(session, DummyModel, "My Project")
    assert value == "my-project"


@pytest.mark.asyncio
async def test_unique_slug_collision_increments_counter() -> None:
    session = AsyncMock()
    first = MagicMock()
    first.scalar_one_or_none.return_value = DummyModel(id=uuid6.uuid7(), slug="my-project")

    second = MagicMock()
    second.scalar_one_or_none.return_value = DummyModel(id=uuid6.uuid7(), slug="my-project-1")

    third = MagicMock()
    third.scalar_one_or_none.return_value = None

    session.execute.side_effect = [first, second, third]

    value = await unique_slug(session, DummyModel, "My Project")
    assert value == "my-project-3"
