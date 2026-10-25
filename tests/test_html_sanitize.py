"""Project long descriptions are stored sanitized; nothing executable survives."""

from __future__ import annotations

import pytest

from app.core.html_sanitize import sanitize_project_html


@pytest.mark.parametrize(
    "raw",
    [
        "<script>alert(1)</script><p>ok</p>",
        '<img src="x" onerror="alert(1)">',
        '<a href="javascript:alert(1)">x</a>',
        '<p style="background:url(javascript:alert(1))">x</p>',
        "<iframe src='https://evil.example'></iframe>",
        "<svg onload=alert(1)>",
        '<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>',
    ],
)
def test_strips_executable_markup(raw: str) -> None:
    cleaned = sanitize_project_html(raw).lower()
    for needle in ("<script", "onerror", "javascript:", "<iframe", "onload", "style=", "data:"):
        assert needle not in cleaned


def test_keeps_blog_markup() -> None:
    raw = (
        '<h2>Title</h2><p><strong>bold</strong> <em>it</em></p>'
        '<ul><li>a</li></ul><a href="https://x.dev">link</a>'
        '<img src="https://x.dev/a.png" alt="a">'
    )
    cleaned = sanitize_project_html(raw)
    assert "<h2>Title</h2>" in cleaned
    assert "<strong>bold</strong>" in cleaned
    assert "<li>a</li>" in cleaned
    assert 'href="https://x.dev"' in cleaned
    assert 'src="https://x.dev/a.png"' in cleaned


def test_links_get_safe_rel() -> None:
    cleaned = sanitize_project_html('<a href="https://x.dev" target="_blank">x</a>')
    assert "noopener" in cleaned


def test_plain_text_becomes_escaped_paragraphs() -> None:
    cleaned = sanitize_project_html("line one\n\nline two & more")
    assert cleaned == "<p>line one</p><p><br></p><p>line two &amp; more</p>"


def test_stray_angle_bracket_is_escaped() -> None:
    assert "&lt;" in sanitize_project_html("a < b <notatag")


@pytest.mark.parametrize("raw", [None, "", "   ", "<script></script>"])
def test_empty_input_gives_empty_paragraph(raw: str | None) -> None:
    assert sanitize_project_html(raw) == "<p></p>"
