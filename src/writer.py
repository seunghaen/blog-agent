"""HTML writer for Stage 4 output."""

from __future__ import annotations

from html import escape


def render_review_html(
    title: str,
    restaurant_name: str,
    visit_date: str,
    paragraphs: list[str],
    info_lines: list[str] | None = None,
) -> str:
    safe_title = escape(title)
    safe_restaurant = escape(restaurant_name)
    safe_visit_date = escape(visit_date)
    safe_info_lines = [escape(item) for item in (info_lines or []) if item.strip()]
    safe_paragraphs = [escape(item) for item in paragraphs if item.strip()]

    info_html = ""
    if safe_info_lines:
        info_items = "".join(f"<li>{line}</li>" for line in safe_info_lines)
        info_html = f"<section><h2>기본 정보</h2><ul>{info_items}</ul></section>"

    body_html = "".join(f"<p>{line}</p>" for line in safe_paragraphs) or "<p></p>"

    return (
        "<!doctype html>"
        "<html lang=\"ko\">"
        "<head>"
        "<meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{safe_title}</title>"
        "</head>"
        "<body>"
        f"<article><h1>{safe_restaurant}</h1><p>{safe_visit_date}</p>{info_html}{body_html}</article>"
        "</body>"
        "</html>"
    )

