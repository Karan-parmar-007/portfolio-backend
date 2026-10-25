from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from uuid import UUID

import uuid6
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.media.model import MediaAsset
from app.config import db_settings, media_settings
from app.core.constants import MEDIA_KIND_PREFIX, MediaKind
from app.core.errors import MediaError, NotFoundError

logger = logging.getLogger(__name__)

_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(raw: str | None) -> str:
    base = os.path.basename(raw or "") or "upload"
    cleaned = _SAFE_FILENAME_RE.sub("_", base).strip("._") or "upload"
    return cleaned[:100]


def _sniff_dimensions(
    content: bytes, content_type: str
) -> tuple[int | None, int | None]:
    """Best-effort PNG/JPEG/WebP/SVG dimension sniffing — no Pillow."""
    try:
        if content_type == "image/png" or content[:8] == b"\x89PNG\r\n\x1a\n":
            if len(content) >= 24 and content[12:16] == b"IHDR":
                width = int.from_bytes(content[16:20], "big")
                height = int.from_bytes(content[20:24], "big")
                return width, height

        if content_type in {"image/jpeg", "image/jpg"} or content[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(content):
                if content[i] != 0xFF:
                    break
                marker = content[i + 1]
                if marker in {
                    0xC0,
                    0xC1,
                    0xC2,
                    0xC3,
                    0xC5,
                    0xC6,
                    0xC7,
                    0xC9,
                    0xCA,
                    0xCB,
                    0xCD,
                    0xCE,
                    0xCF,
                }:
                    height = int.from_bytes(content[i + 5 : i + 7], "big")
                    width = int.from_bytes(content[i + 7 : i + 9], "big")
                    return width, height
                length = int.from_bytes(content[i + 2 : i + 4], "big")
                i += 2 + length

        if content_type == "image/webp" or content[:4] == b"RIFF":
            if len(content) >= 30 and content[8:12] == b"WEBP":
                if content[12:16] == b"VP8X" and len(content) >= 30:
                    width = 1 + int.from_bytes(content[24:27], "little")
                    height = 1 + int.from_bytes(content[27:30], "little")
                    return width, height
                if content[12:16] == b"VP8 " and len(content) >= 30:
                    width = int.from_bytes(content[26:28], "little") & 0x3FFF
                    height = int.from_bytes(content[28:30], "little") & 0x3FFF
                    return width, height
                if content[12:16] == b"VP8L" and len(content) >= 25:
                    bits = int.from_bytes(content[21:25], "little")
                    width = (bits & 0x3FFF) + 1
                    height = ((bits >> 14) & 0x3FFF) + 1
                    return width, height

        if content_type == "image/svg+xml" or b"<svg" in content[:512].lower():
            text = content[:4096].decode("utf-8", errors="ignore")
            vb = re.search(
                r'viewBox\s*=\s*["\']?\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)',
                text,
                re.IGNORECASE,
            )
            if vb:
                return int(float(vb.group(3))), int(float(vb.group(4)))
            w = re.search(r'\bwidth\s*=\s*["\']?(\d+)', text, re.IGNORECASE)
            h = re.search(r'\bheight\s*=\s*["\']?(\d+)', text, re.IGNORECASE)
            if w and h:
                return int(w.group(1)), int(h.group(1))
    except Exception:
        logger.debug("Dimension sniff failed", exc_info=True)
    return None, None


class MediaService:
    def __init__(self, pg_session: AsyncSession, garage_client: object) -> None:
        self.pg_session = pg_session
        self.garage_client = garage_client
        self._bucket = db_settings.GARAGE_BUCKET_NAME

    def _allowed_types(self, kind: MediaKind) -> set[str]:
        if kind == MediaKind.RESUME:
            return media_settings.allowed_document_types
        return media_settings.allowed_image_types

    def _max_bytes(self, kind: MediaKind) -> int:
        if kind == MediaKind.RESUME:
            return media_settings.MEDIA_MAX_DOCUMENT_BYTES
        return media_settings.MEDIA_MAX_IMAGE_BYTES

    async def store(self, file: UploadFile, kind: MediaKind) -> MediaAsset:
        content = await file.read()
        return await self.store_bytes(
            content,
            filename=file.filename,
            content_type=file.content_type,
            kind=kind,
        )

    async def store_bytes(
        self,
        content: bytes,
        *,
        filename: str | None,
        content_type: str | None,
        kind: MediaKind,
        commit: bool = True,
    ) -> MediaAsset:
        """Validate, upload and record bytes.

        With `commit=False` the row is only flushed: the caller owns the
        transaction and must delete `asset.object_key` if it rolls back.
        """
        if not content:
            raise MediaError("File is empty")

        content_type = (content_type or "").split(";")[0].strip().lower()
        allowed = self._allowed_types(kind)
        if content_type not in allowed:
            raise MediaError(
                f"Content type '{content_type}' is not allowed for {kind.value}"
            )

        max_bytes = self._max_bytes(kind)
        if len(content) > max_bytes:
            raise MediaError(
                f"File exceeds maximum size of {max_bytes} bytes for {kind.value}"
            )

        checksum = hashlib.sha256(content).hexdigest()
        existing = (
            await self.pg_session.execute(
                select(MediaAsset).where(
                    MediaAsset.checksum_sha256 == checksum,
                    MediaAsset.kind == kind,
                )
                .limit(1)
            )
        ).scalars().first()
        if existing is not None:
            return existing

        width, height = (None, None)
        if kind != MediaKind.RESUME:
            width, height = _sniff_dimensions(content, content_type)

        media_id = uuid6.uuid7()
        filename = _safe_filename(filename)
        prefix = MEDIA_KIND_PREFIX[kind]
        object_key = f"{prefix}/{media_id}/{filename}"

        await self.garage_client.put_object(
            Bucket=self._bucket,
            Key=object_key,
            Body=content,
            ContentType=content_type,
        )

        asset = MediaAsset(
            id=media_id,
            object_key=object_key,
            filename=filename,
            content_type=content_type,
            size_bytes=len(content),
            kind=kind,
            checksum_sha256=checksum,
            width=width,
            height=height,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        self.pg_session.add(asset)
        try:
            if not commit:
                await self.pg_session.flush()
                return asset
            await self.pg_session.commit()
            await self.pg_session.refresh(asset)
        except Exception:
            await self.pg_session.rollback()
            try:
                await self.garage_client.delete_object(
                    Bucket=self._bucket, Key=object_key
                )
            except Exception as cleanup_exc:
                logger.error(
                    "Failed to delete orphan Garage object %s: %s",
                    object_key,
                    cleanup_exc,
                )
            raise

        logger.info("Stored media %s kind=%s key=%s", media_id, kind.value, object_key)
        return asset

    async def replace(
        self,
        file: UploadFile,
        kind: MediaKind,
        old_media_id: UUID | None,
    ) -> MediaAsset:
        """Store new asset first; caller updates FK then we delete the old one."""
        new_asset = await self.store(file, kind)
        if old_media_id is not None and old_media_id != new_asset.id:
            await self.delete(old_media_id)
        return new_asset

    async def get(self, media_id: UUID) -> MediaAsset:
        asset = (
            await self.pg_session.execute(
                select(MediaAsset).where(MediaAsset.id == media_id)
            )
        ).scalar_one_or_none()
        if asset is None:
            raise NotFoundError("Media not found")
        return asset

    async def get_content(self, media_id: UUID) -> tuple[MediaAsset, bytes]:
        asset = await self.get(media_id)
        response = await self.garage_client.get_object(
            Bucket=self._bucket, Key=asset.object_key
        )
        content = await response["Body"].read()
        return asset, content

    async def delete(self, media_id: UUID) -> None:
        asset = (
            await self.pg_session.execute(
                select(MediaAsset).where(MediaAsset.id == media_id)
            )
        ).scalar_one_or_none()
        if asset is None:
            return

        try:
            await self.garage_client.delete_object(
                Bucket=self._bucket, Key=asset.object_key
            )
        except Exception as exc:
            logger.warning(
                "Garage object missing or delete failed for %s: %s",
                asset.object_key,
                exc,
            )

        await self.pg_session.delete(asset)
        await self.pg_session.commit()
        logger.info("Deleted media %s", media_id)
