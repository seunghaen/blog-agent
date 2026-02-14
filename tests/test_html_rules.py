from __future__ import annotations

from src.rules import validate_html_document


def test_html_rules_detect_banned_elements() -> None:
    html = (
        "<html><head><title>x</title></head>"
        "<body>hello ** <hr> image/gif 😀</body></html>"
    )
    report = validate_html_document(html, recent_review_count=1)
    assert report.passed is False
    assert any("**" in item for item in report.violations)
    assert any("<hr" in item for item in report.violations)
    assert any("image/gif" in item for item in report.violations)
    assert any("emoji" in item for item in report.violations)


def test_html_rules_detect_review_reference_without_recent_reviews() -> None:
    html = (
        "<html><head><title>x</title></head>"
        "<body><p>최근 리뷰에서 분위기가 좋았다고 합니다.</p></body></html>"
    )
    report = validate_html_document(html, recent_review_count=0)
    assert report.passed is False
    assert any("mentions reviews without recent review data" in item for item in report.violations)


def test_html_rules_pass_for_valid_html() -> None:
    html = (
        "<!doctype html><html><head><title>x</title></head>"
        "<body><article><p>사진 기반으로 조심스럽게 정리했습니다.</p></article></body></html>"
    )
    report = validate_html_document(html, recent_review_count=0)
    assert report.passed is True
    assert report.violations == []


def test_html_rules_detect_quoted_full_sentence_emphasis() -> None:
    html = (
        "<html><head><title>x</title></head>"
        "<body><p>\"정말 최고였다\"</p></body></html>"
    )
    report = validate_html_document(html, recent_review_count=1)
    assert report.passed is False
    assert any("quoted full-sentence emphasis" in item for item in report.violations)
