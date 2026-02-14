"""Vision client interfaces and normalized models for Stage 3."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
import re
from typing import Any, Protocol
from urllib.request import Request, urlopen

GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
)


@dataclass(frozen=True)
class VisionAnalysis:
    scene_type: str = "other"
    observations: list[str] = field(default_factory=list)
    food_guess: list[str] = field(default_factory=list)
    ambience_hints: list[str] = field(default_factory=list)
    bloggable_details: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scene_type": self.scene_type,
            "observations": self.observations,
            "food_guess": self.food_guess,
            "ambience_hints": self.ambience_hints,
            "bloggable_details": self.bloggable_details,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class VisionImageResult:
    file_id: str
    name: str
    analysis: VisionAnalysis | None = None
    raw: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"file_id": self.file_id, "name": self.name}
        if self.analysis is not None:
            payload["analysis"] = self.analysis.to_dict()
        if self.raw is not None:
            payload["_raw"] = self.raw
        return payload


class VisionProviderProtocol(Protocol):
    def analyze_image(
        self,
        file_id: str,
        image_name: str,
        mime_type: str | None = None,
        image_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        """Return model response in provider-specific format."""


class VisionClient:
    def __init__(self, provider: VisionProviderProtocol | None) -> None:
        self._provider = provider

    def analyze(
        self,
        file_id: str,
        image_name: str,
        mime_type: str | None = None,
        image_bytes: bytes | None = None,
    ) -> VisionImageResult:
        if not self._provider:
            return VisionImageResult(
                file_id=file_id,
                name=image_name,
                raw="vision provider not configured",
            )

        try:
            raw_payload = self._provider.analyze_image(
                file_id=file_id,
                image_name=image_name,
                mime_type=mime_type,
                image_bytes=image_bytes,
            )
        except Exception as exc:
            return VisionImageResult(
                file_id=file_id,
                name=image_name,
                raw=f"vision analyze failed: {exc}",
            )
        analysis = VisionAnalysis(
            scene_type=str(raw_payload.get("scene_type", "other")),
            observations=list(raw_payload.get("observations") or []),
            food_guess=list(raw_payload.get("food_guess") or []),
            ambience_hints=list(raw_payload.get("ambience_hints") or []),
            bloggable_details=list(raw_payload.get("bloggable_details") or []),
            warnings=list(raw_payload.get("warnings") or []),
        )
        return VisionImageResult(file_id=file_id, name=image_name, analysis=analysis)


class GeminiVisionProvider(VisionProviderProtocol):
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        prompt: str | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("vision api key is empty")
        self._api_key = api_key.strip()
        self._model = model
        self._prompt = prompt or (
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

    def analyze_image(
        self,
        file_id: str,
        image_name: str,
        mime_type: str | None = None,
        image_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        if not image_bytes:
            return {
                "scene_type": "other",
                "observations": [],
                "food_guess": [],
                "ambience_hints": [],
                "bloggable_details": [],
                "warnings": [f"image bytes unavailable for {image_name}"],
            }

        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": self._prompt},
                        {
                            "inlineData": {
                                "mimeType": mime_type or "image/jpeg",
                                "data": encoded_image,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }

        raw_response = _http_post_json(
            GEMINI_GENERATE_URL.format(model=self._model, api_key=self._api_key),
            payload=payload,
        )
        text = _extract_candidate_text(raw_response)
        parsed = _parse_json_like_text(text)
        return _normalize_analysis(parsed, fallback_warning=f"vision parse fallback for {image_name}")


def _http_post_json(url: str, payload: dict[str, Any], timeout_sec: float = 30.0) -> dict[str, Any]:
    request = Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout_sec) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("vision response is not a JSON object")
    return parsed


def _extract_candidate_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return json.dumps(payload, ensure_ascii=False)
    top = candidates[0]
    content = top.get("content") if isinstance(top, dict) else {}
    parts = content.get("parts") if isinstance(content, dict) else []
    if not isinstance(parts, list):
        return json.dumps(payload, ensure_ascii=False)

    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            chunks.append(part["text"])
    return "\n".join(chunks).strip() or json.dumps(payload, ensure_ascii=False)


def _parse_json_like_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if fenced:
        parsed = json.loads(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        candidate = stripped[first : last + 1]
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("unable to parse vision response as JSON")


def _normalize_analysis(payload: dict[str, Any], fallback_warning: str) -> dict[str, Any]:
    def _as_list(key: str) -> list[str]:
        value = payload.get(key, [])
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    scene_type = str(payload.get("scene_type", "other")).strip().lower() or "other"
    allowed_scene_types = {"food", "menu", "interior", "exterior", "receipt", "other"}
    if scene_type not in allowed_scene_types:
        scene_type = "other"

    warnings = _as_list("warnings")
    if not warnings:
        warnings = [fallback_warning]

    return {
        "scene_type": scene_type,
        "observations": _as_list("observations"),
        "food_guess": _as_list("food_guess"),
        "ambience_hints": _as_list("ambience_hints"),
        "bloggable_details": _as_list("bloggable_details"),
        "warnings": warnings,
    }
