# app/core/html_sanitize.py
"""Allowlist sanitizer for project long descriptions (rich text from the admin)."""

from __future__ import annotations

import html

import nh3

_ALLOWED_TAGS = {
    "p", "br", "h2", "h3", "h4", "strong", "b", "em", "i", "u", "s", "a",
    "ul", "ol", "li", "blockquote", "img", "code", "pre", "hr", "span",
    "figure", "figcaption",
}
_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title"},
}
_EMPTY = "<p></p>"


def sanitize_project_html(raw: str | None) -> str:
    """Keep blog-style markup; drop scripts, handlers, styles and unsafe URLs."""
    text = (raw or "").strip()
    if not text:
        return _EMPTY
    if "<" not in text:
        lines = html.escape(text, quote=False).split("\n")
        return "".join(f"<p>{line}</p>" if line.strip() else "<p><br></p>" for line in lines)
    cleaned = nh3.clean(
        text,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
        strip_comments=True,
    ).strip()
    return cleaned or _EMPTY
