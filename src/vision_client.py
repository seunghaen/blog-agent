"""Vision client interfaces and normalized models for Stage 3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


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
    def analyze_image(self, file_id: str, image_name: str) -> dict[str, Any]:
        """Return model response in provider-specific format."""


class VisionClient:
    def __init__(self, provider: VisionProviderProtocol | None) -> None:
        self._provider = provider

    def analyze(self, file_id: str, image_name: str) -> VisionImageResult:
        if not self._provider:
            return VisionImageResult(
                file_id=file_id,
                name=image_name,
                raw="vision provider not configured",
            )

        raw_payload = self._provider.analyze_image(file_id=file_id, image_name=image_name)
        analysis = VisionAnalysis(
            scene_type=str(raw_payload.get("scene_type", "other")),
            observations=list(raw_payload.get("observations") or []),
            food_guess=list(raw_payload.get("food_guess") or []),
            ambience_hints=list(raw_payload.get("ambience_hints") or []),
            bloggable_details=list(raw_payload.get("bloggable_details") or []),
            warnings=list(raw_payload.get("warnings") or []),
        )
        return VisionImageResult(file_id=file_id, name=image_name, analysis=analysis)

