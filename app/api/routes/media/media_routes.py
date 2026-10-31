from __future__ import annotations

import re
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies import MediaServiceDep
from app.config import media_settings

router = APIRouter(prefix="/media", tags=["media"])


def _etag(checksum: str) -> str:
    return f'"{checksum}"'


_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_NAME = 80


def _download_name(requested: str | None, stored: str) -> str:
    """The caller's name (cleaned) plus the stored file's real extension.

    Only letters, digits, `_` and `-` survive, so the name can't break the
    header or change the file type. Nothing usable left: keep the stored name.
    """
    suffix = PurePosixPath(stored).suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", suffix):
        suffix = ""
    clean = _UNSAFE_NAME.sub("_", requested or "").strip("_-")[:_MAX_NAME].strip("_-")
    if clean:
        return f"{clean}{suffix}"
    return stored.encode("ascii", "ignore").decode().replace('"', "").replace("\\", "") or f"download{suffix}"


def _cache_headers(asset_checksum: str, size_bytes: int | None = None) -> dict[str, str]:
    headers = {
        "ETag": _etag(asset_checksum),
        "Cache-Control": (
            f"public, max-age={media_settings.MEDIA_CACHE_MAX_AGE_SECONDS}, immutable"
        ),
    }
    if size_bytes is not None:
        headers["Content-Length"] = str(size_bytes)
    return headers


@router.get("/{media_id}")
async def get_media(
    media_id: UUID,
    request: Request,
    service: MediaServiceDep,
) -> Response:
    asset = await service.get(media_id)
    etag = _etag(asset.checksum_sha256)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip() == etag:
        return Response(
            status_code=304,
            headers=_cache_headers(asset.checksum_sha256),
        )

    asset, content = await service.get_content(media_id)
    return Response(
        content=content,
        media_type=asset.content_type,
        headers=_cache_headers(asset.checksum_sha256, asset.size_bytes),
    )


@router.get("/{media_id}/download")
async def download_media(
    media_id: UUID,
    request: Request,
    service: MediaServiceDep,
    name: str | None = Query(default=None, max_length=500),
) -> Response:
    asset = await service.get(media_id)
    etag = _etag(asset.checksum_sha256)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip() == etag:
        return Response(
            status_code=304,
            headers=_cache_headers(asset.checksum_sha256),
        )

    asset, content = await service.get_content(media_id)
    headers = _cache_headers(asset.checksum_sha256, asset.size_bytes)
    filename = _download_name(name, asset.filename)
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(
        content=content,
        media_type=asset.content_type,
        headers=headers,
    )
