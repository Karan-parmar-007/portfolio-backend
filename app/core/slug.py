# app/core/slug.py
from __future__ import annotations

from uuid import UUID

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def unique_slug(
    session: AsyncSession,
    model: type,
    base: str,
    *,
    exclude_id: UUID | None = None,
) -> str:
    """Return a unique slug for `model.slug`, appending -2, -3, ... as needed."""
    candidate = slugify(base) or "item"
    slug_col = getattr(model, "slug")
    n = 1
    while True:
        value = candidate if n == 1 else f"{candidate}-{n}"
        stmt = select(model.id).where(slug_col == value)
        if exclude_id is not None:
            stmt = stmt.where(model.id != exclude_id)
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            return value
        n += 1
