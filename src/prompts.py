"""Prompt and text template management."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
from typing import Any

DEFAULT_VISION_PROMPT = (
    "Analyze this restaurant-related image and return ONLY JSON with this schema: "
    "{"
    "\"scene_type\":\"food|menu|interior|exterior|receipt|other\","
    "\"observations\":[\"...\"],"
    "\"food_guess\":[\"... (estimated)\"],"
    "\"ambience_hints\":[\"...\"],"
    "\"bloggable_details\":[\"...\"],"
    "\"warnings\":[\"...\"]"
    "}."
    " Keep each list short and factual. If uncertain, mention uncertainty in warnings."
)


@dataclass(frozen=True)
class PromptSet:
    vision_prompt: str = DEFAULT_VISION_PROMPT
    title_template: str = "{restaurant_name} 방문 기록"
    intro_template: str = "{visit_date} 방문 사진 {image_count}장을 기준으로 정리했습니다."
    scene_summary_template: str = "사진에서 확인된 장면은 {scene_text}입니다."
    observations_prefix: str = "사진 관찰 포인트: "
    food_guess_prefix: str = "음식 추정: "
    recent_review_template: str = (
        "최근 60일 기준 공개 의견 {review_count}건이 확인되며, 예시로 {summary} 같은 반응이 보입니다."
    )
    fallback_paragraph: str = "사진에서 확인 가능한 범위 안에서만 내용을 구성했습니다."
    missing_info_line: str = "식당 기본 정보는 확인되지 않아 사진 기준으로만 정리했습니다."


def load_prompts(prompt_file: str | None) -> PromptSet:
    if not prompt_file:
        return PromptSet()
    path = Path(prompt_file)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Prompt file not found: {prompt_file}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prompt file must contain a JSON object")
    return _merge_prompts(PromptSet(), payload)


def _merge_prompts(base: PromptSet, payload: dict[str, Any]) -> PromptSet:
    mapping = {
        "vision_prompt": "vision_prompt",
        "title_template": "title_template",
        "intro_template": "intro_template",
        "scene_summary_template": "scene_summary_template",
        "observations_prefix": "observations_prefix",
        "food_guess_prefix": "food_guess_prefix",
        "recent_review_template": "recent_review_template",
        "fallback_paragraph": "fallback_paragraph",
        "missing_info_line": "missing_info_line",
    }
    updates: dict[str, Any] = {}
    for src_key, field_name in mapping.items():
        value = payload.get(src_key)
        if isinstance(value, str) and value.strip():
            updates[field_name] = value
    if not updates:
        return base
    return replace(base, **updates)

