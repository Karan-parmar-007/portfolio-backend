from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response

from app.api.dependencies import MediaServiceDep
from app.config import media_settings

router = APIRouter(prefix="/media", tags=["media"])


def _etag(checksum: str) -> str:
    return f'"{checksum}"'


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
    headers["Content-Disposition"] = f'attachment; filename="{asset.filename}"'
    return Response(
        content=content,
        media_type=asset.content_type,
        headers=headers,
    )
