from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.api.routes.media.model import MediaAsset


class MediaRef(BaseModel):
    id: UUID
    url: str
    filename: str
    content_type: str
    width: int | None = None
    height: int | None = None


def media_asset_to_ref(asset: MediaAsset | None) -> MediaRef | None:
    """Convert a MediaAsset row into the public MediaRef shape."""
    if asset is None:
        return None
    return MediaRef(
        id=asset.id,
        url=f"/api/portfolio/media/{asset.id}",
        filename=asset.filename,
        content_type=asset.content_type,
        width=asset.width,
        height=asset.height,
    )


def media_ref_from_id(
    media_id: UUID | None,
    *,
    filename: str = "",
    content_type: str = "",
    width: int | None = None,
    height: int | None = None,
) -> MediaRef | None:
    if media_id is None:
        return None
    return MediaRef(
        id=media_id,
        url=f"/api/portfolio/media/{media_id}",
        filename=filename,
        content_type=content_type,
        width=width,
        height=height,
    )
