"""Request validation for the project admin API."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes.project.project_constants import ProjectStatus
from app.api.routes.project.project_schemas import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
)


def _create(**overrides: object) -> ProjectCreateRequest:
    data: dict[str, object] = {"name": "Maps", "short_description": "Scrapes maps"}
    data.update(overrides)
    return ProjectCreateRequest.model_validate(data)


def test_defaults() -> None:
    body = _create()
    assert body.status is ProjectStatus.OFFLINE
    assert body.is_featured is False
    assert body.tech_stack == []
    assert body.tags == []
    assert body.github_url is None
    assert body.try_url is None


def test_name_and_description_are_trimmed_and_required() -> None:
    assert _create(name="  Maps  ").name == "Maps"
    with pytest.raises(ValidationError):
        _create(name="   ")
    with pytest.raises(ValidationError):
        _create(short_description="")


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,hi",
        "ftp://x.dev",
        "//evil.example",
        "/relative/path",
        "https://",
        "https://x.dev/" + "a" * 600,
    ],
)
def test_rejects_unsafe_or_invalid_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        _create(try_url=url)
    with pytest.raises(ValidationError):
        _create(github_url=url)


def test_blank_url_becomes_none() -> None:
    assert _create(try_url="  ", github_url="").try_url is None


def test_accepts_https_url() -> None:
    body = _create(try_url=" https://studio.karanparmar.in/products/gmaps ")
    assert body.try_url == "https://studio.karanparmar.in/products/gmaps"


def test_tech_stack_and_tags_are_cleaned_and_deduped() -> None:
    body = _create(
        tech_stack=[" Python", "python", "", "FastAPI ", "Python"],
        tags=["AI", " ai ", "Web"],
    )
    assert body.tech_stack == ["Python", "FastAPI"]
    assert body.tags == ["AI", "Web"]


def test_tech_stack_limits() -> None:
    with pytest.raises(ValidationError):
        _create(tech_stack=[f"t{i}" for i in range(31)])
    with pytest.raises(ValidationError):
        _create(tech_stack=["x" * 51])
    with pytest.raises(ValidationError):
        _create(tags=["x" * 51])


def test_status_must_be_one_of_three() -> None:
    assert _create(status="archived").status is ProjectStatus.ARCHIVED
    for bad in ("hidden", "maintenance", "LIVE", ""):
        with pytest.raises(ValidationError):
            _create(status=bad)


def test_update_is_partial() -> None:
    body = ProjectUpdateRequest.model_validate({"status": "live"})
    assert body.model_dump(exclude_unset=True) == {"status": ProjectStatus.LIVE}
    with pytest.raises(ValidationError):
        ProjectUpdateRequest.model_validate({"name": "  "})
    with pytest.raises(ValidationError):
        ProjectUpdateRequest.model_validate({"try_url": "javascript:x"})
