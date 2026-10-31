"""GET /media/{id}/download: attachment with a clean, caller-chosen file name."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.api.dependencies import get_media_service

MEDIA_ID = uuid4()
ASSET = SimpleNamespace(
    id=MEDIA_ID,
    filename="01a0d1f3-82ca-72d7-resume_final_v3.pdf",
    content_type="application/pdf",
    checksum_sha256="abc123",
    size_bytes=4,
)


class FakeMediaService:
    async def get(self, media_id):
        return ASSET

    async def get_content(self, media_id):
        return ASSET, b"%PDF"


@pytest.fixture(autouse=True)
def _override() -> Iterator[None]:
    from main import app

    app.dependency_overrides[get_media_service] = FakeMediaService
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _disposition(response: httpx.Response) -> str:
    return response.headers["content-disposition"]


async def test_name_sets_the_downloaded_file_name(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get(
        f"/api/portfolio/media/{MEDIA_ID}/download", params={"name": "karan_parmar_resume"}
    )
    assert response.status_code == 200
    assert response.content == b"%PDF"
    assert _disposition(response).startswith("attachment;")
    assert 'filename="karan_parmar_resume.pdf"' in _disposition(response)


async def test_without_a_name_the_stored_name_is_used(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get(f"/api/portfolio/media/{MEDIA_ID}/download")
    assert response.status_code == 200
    assert 'filename="01a0d1f3-82ca-72d7-resume_final_v3.pdf"' in _disposition(response)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Karan Parmar Resume", "Karan_Parmar_Resume.pdf"),
        ('evil"; filename="x.exe', "evil_filename_x_exe.pdf"),
        ("../../etc/passwd", "etc_passwd.pdf"),
        ("resume.exe", "resume_exe.pdf"),
        ("x" * 300, "x" * 80 + ".pdf"),
    ],
)
async def test_unsafe_names_are_cleaned_and_keep_the_real_extension(
    app_client: httpx.AsyncClient, name: str, expected: str
) -> None:
    response = await app_client.get(
        f"/api/portfolio/media/{MEDIA_ID}/download", params={"name": name}
    )
    assert response.status_code == 200
    assert f'filename="{expected}"' in _disposition(response)


async def test_a_name_with_nothing_usable_falls_back_to_the_stored_name(
    app_client: httpx.AsyncClient,
) -> None:
    response = await app_client.get(
        f"/api/portfolio/media/{MEDIA_ID}/download", params={"name": "../---"}
    )
    assert response.status_code == 200
    assert 'filename="01a0d1f3-82ca-72d7-resume_final_v3.pdf"' in _disposition(response)


async def test_a_non_ascii_stored_name_still_downloads(app_client: httpx.AsyncClient) -> None:
    ASSET.filename, original = "résumé करण.pdf", ASSET.filename
    try:
        response = await app_client.get(f"/api/portfolio/media/{MEDIA_ID}/download")
    finally:
        ASSET.filename = original
    assert response.status_code == 200
    assert 'filename="rsum .pdf"' in _disposition(response)
