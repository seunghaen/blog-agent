"""Places client interfaces and normalized models for Stage 2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class RestaurantReview:
    time: int
    rating: int | float
    text: str
    relative_time: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time,
            "rating": self.rating,
            "text": self.text,
            "relative_time": self.relative_time,
        }


@dataclass(frozen=True)
class RestaurantInfo:
    found: bool
    place_id: str = ""
    name: str = ""
    address: str = ""
    opening_hours: list[str] = field(default_factory=list)
    rating: float | None = None
    user_ratings_total: int | None = None
    maps_url: str = ""
    website: str = ""
    recent_reviews: list[RestaurantReview] = field(default_factory=list)
    recent_reviews_cutoff_days: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "place_id": self.place_id,
            "name": self.name,
            "address": self.address,
            "opening_hours": self.opening_hours,
            "rating": self.rating,
            "user_ratings_total": self.user_ratings_total,
            "maps_url": self.maps_url,
            "website": self.website,
            "recent_reviews": [item.to_dict() for item in self.recent_reviews],
            "recent_reviews_cutoff_days": self.recent_reviews_cutoff_days,
        }


class PlacesProviderProtocol(Protocol):
    def search_place(self, restaurant_name: str) -> dict[str, Any] | None:
        """Search place and return at least a place_id when found."""

    def get_place_details(self, place_id: str) -> dict[str, Any] | None:
        """Return place details with optional reviews field."""


class PlacesClient:
    """Thin adapter to keep Stage 2 logic independent from API vendors."""

    def __init__(
        self,
        provider: PlacesProviderProtocol | None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self._provider = provider
        self._now_fn = now_fn or (lambda: datetime.now(timezone.utc))

    def fetch_restaurant_info(
        self,
        restaurant_name: str,
        cutoff_days: int = 60,
    ) -> RestaurantInfo:
        if not self._provider:
            return RestaurantInfo(found=False, recent_reviews_cutoff_days=cutoff_days)

        found = self._provider.search_place(restaurant_name)
        if not found:
            return RestaurantInfo(found=False, recent_reviews_cutoff_days=cutoff_days)

        place_id = str(found.get("place_id") or found.get("placeId") or "").strip()
        if not place_id:
            return RestaurantInfo(found=False, recent_reviews_cutoff_days=cutoff_days)

        details = self._provider.get_place_details(place_id) or {}
        recent_reviews = self._filter_recent_reviews(details.get("reviews"), cutoff_days)
        return RestaurantInfo(
            found=True,
            place_id=place_id,
            name=str(details.get("name") or restaurant_name),
            address=str(details.get("address", "")),
            opening_hours=list(details.get("opening_hours") or []),
            rating=_safe_float(details.get("rating")),
            user_ratings_total=_safe_int(details.get("user_ratings_total")),
            maps_url=str(details.get("maps_url", "")),
            website=str(details.get("website", "")),
            recent_reviews=recent_reviews,
            recent_reviews_cutoff_days=cutoff_days,
        )

    def _filter_recent_reviews(
        self, reviews: list[dict[str, Any]] | None, cutoff_days: int
    ) -> list[RestaurantReview]:
        if not reviews:
            return []
        if cutoff_days < 1:
            return []

        now_ts = int(self._now_fn().timestamp())
        cutoff_ts = now_ts - cutoff_days * 24 * 60 * 60

        result: list[RestaurantReview] = []
        for review in reviews:
            review_ts = _safe_int(review.get("time"))
            if review_ts is None or review_ts < cutoff_ts:
                continue
            result.append(
                RestaurantReview(
                    time=review_ts,
                    rating=review.get("rating", 0),
                    text=str(review.get("text", "")),
                    relative_time=str(review.get("relative_time", "")),
                )
            )
        return result


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

