"""Unit tests for MediaService validation and dimension sniffing."""

from __future__ import annotations

import struct
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import UploadFile

from app.api.routes.media.media_service import MediaService, _sniff_dimensions
from app.config import media_settings
from app.core.constants import MediaKind
from app.core.errors import MediaError
from tests.conftest import FakeGarageClient


def _png_bytes(width: int = 2, height: int = 3) -> bytes:
    """Minimal PNG with IHDR so _sniff_dimensions can read size."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = struct.pack(">I", 13) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return sig + chunk


def _upload(content: bytes, *, filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers={"content-type": content_type},
    )


def _mock_session_no_duplicate() -> AsyncMock:
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_store_rejects_empty_file(fake_garage_client: FakeGarageClient) -> None:
    service = MediaService(_mock_session_no_duplicate(), fake_garage_client)
    upload = _upload(b"", filename="empty.png", content_type="image/png")

    with pytest.raises(MediaError, match="empty"):
        await service.store(upload, MediaKind.PROFILE_IMAGE)


@pytest.mark.asyncio
async def test_store_rejects_bad_content_type(
    fake_garage_client: FakeGarageClient,
) -> None:
    service = MediaService(_mock_session_no_duplicate(), fake_garage_client)
    upload = _upload(b"not-an-image", filename="x.txt", content_type="text/plain")

    with pytest.raises(MediaError, match="not allowed"):
        await service.store(upload, MediaKind.PROJECT_COVER)


@pytest.mark.asyncio
async def test_store_rejects_oversized_file(
    fake_garage_client: FakeGarageClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_settings, "MEDIA_MAX_IMAGE_BYTES", 8)
    service = MediaService(_mock_session_no_duplicate(), fake_garage_client)
    upload = _upload(
        b"0123456789",
        filename="big.png",
        content_type="image/png",
    )

    with pytest.raises(MediaError, match="maximum size"):
        await service.store(upload, MediaKind.SKILL_ICON)


def test_sniff_dimensions_png() -> None:
    content = _png_bytes(12, 34)
    width, height = _sniff_dimensions(content, "image/png")
    assert width == 12
    assert height == 34


def test_sniff_dimensions_svg_viewbox() -> None:
    svg = b'<svg viewBox="0 0 100 50" xmlns="http://www.w3.org/2000/svg"></svg>'
    width, height = _sniff_dimensions(svg, "image/svg+xml")
    assert width == 100
    assert height == 50


def test_sniff_dimensions_unknown_returns_none() -> None:
    width, height = _sniff_dimensions(b"garbage", "application/octet-stream")
    assert width is None
    assert height is None
