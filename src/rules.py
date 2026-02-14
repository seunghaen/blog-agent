"""Output validation rules for Stage 4."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

BANNED_LITERALS = ("**", "<hr", ".gif", "image/gif")
REVIEW_REFERENCE_KEYWORDS = ("최근 리뷰", "리뷰에서", "review")
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "]+"
)


@dataclass(frozen=True)
class RulesReport:
    passed: bool
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {"passed": self.passed, "violations": self.violations}


def validate_html_document(html_text: str, recent_review_count: int = 0) -> RulesReport:
    violations: list[str] = []
    lowered = html_text.lower()

    if "<html" not in lowered:
        violations.append("missing <html> tag")
    if "<head" not in lowered:
        violations.append("missing <head> tag")
    if "<body" not in lowered:
        violations.append("missing <body> tag")

    for literal in BANNED_LITERALS:
        if literal in lowered:
            violations.append(f"contains banned token: {literal}")

    if EMOJI_PATTERN.search(html_text):
        violations.append("contains emoji")

    if recent_review_count == 0:
        for keyword in REVIEW_REFERENCE_KEYWORDS:
            if keyword.lower() in lowered:
                violations.append(f"mentions reviews without recent review data: {keyword}")
                break

    return RulesReport(passed=not violations, violations=violations)


def assert_stage(stage: int) -> None:
    if stage not in {1, 2, 3, 4}:
        raise ValueError("stage must be one of: 1, 2, 3, 4")

