"""Folder scanning interfaces and shared data models for Stage 1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Protocol, Sequence

SUPPORTED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
FOLDER_NAME_PATTERN = re.compile(r"^(?P<visit_date>\d{8})_(?P<restaurant_name>.+)$")
DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class ParsedFolderName:
    visit_date: str
    restaurant_name: str

    @property
    def visit_datetime(self) -> datetime:
        return datetime.strptime(self.visit_date, "%Y%m%d")


@dataclass(frozen=True)
class ImageEntry:
    file_id: str
    name: str
    mime_type: str

    def to_dict(self) -> dict[str, str]:
        return {
            "file_id": self.file_id,
            "name": self.name,
            "mime_type": self.mime_type,
        }


@dataclass(frozen=True)
class SourceFolderEntry:
    folder_id: str
    folder_name: str


@dataclass(frozen=True)
class Manifest:
    source_folder_id: str
    source_folder_name: str
    visit_date: str
    restaurant_name: str
    images: list[ImageEntry]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_folder_id": self.source_folder_id,
            "source_folder_name": self.source_folder_name,
            "visit_date": self.visit_date,
            "restaurant_name": self.restaurant_name,
            "images": [image.to_dict() for image in self.images],
        }


class DriveClientProtocol(Protocol):
    def list_children(self, folder_id: str) -> list[dict[str, str]]:
        """Return child files/folders with at least: id, name, mimeType."""


def parse_source_folder_name(folder_name: str) -> ParsedFolderName:
    match = FOLDER_NAME_PATTERN.match(folder_name)
    if not match:
        raise ValueError(f"Invalid source folder format: {folder_name}")

    visit_date = match.group("visit_date")
    restaurant_name = match.group("restaurant_name").strip()
    if not restaurant_name:
        raise ValueError(f"Restaurant name is empty: {folder_name}")

    # Validate date by parsing.
    datetime.strptime(visit_date, "%Y%m%d")
    return ParsedFolderName(visit_date=visit_date, restaurant_name=restaurant_name)


def select_latest_folders(folder_names: Sequence[str], latest: int) -> list[ParsedFolderName]:
    if latest < 1:
        raise ValueError("latest must be >= 1")

    parsed = [parse_source_folder_name(name) for name in folder_names]
    parsed.sort(key=lambda item: item.visit_date, reverse=True)
    return parsed[:latest]


def list_source_folders(
    drive_client: DriveClientProtocol, input_root_id: str
) -> list[SourceFolderEntry]:
    candidates: list[SourceFolderEntry] = []
    for entry in drive_client.list_children(input_root_id):
        folder_id = entry.get("id", "").strip()
        folder_name = entry.get("name", "").strip()
        mime_type = entry.get("mimeType", "").strip()
        if mime_type != DRIVE_FOLDER_MIME_TYPE:
            continue
        if not folder_id or not folder_name:
            continue
        try:
            parse_source_folder_name(folder_name)
        except ValueError:
            continue
        candidates.append(SourceFolderEntry(folder_id=folder_id, folder_name=folder_name))
    return candidates


def select_latest_source_folders(
    source_folders: Sequence[SourceFolderEntry], latest: int
) -> list[SourceFolderEntry]:
    if latest < 1:
        raise ValueError("latest must be >= 1")

    enriched: list[tuple[str, SourceFolderEntry]] = []
    for item in source_folders:
        parsed = parse_source_folder_name(item.folder_name)
        enriched.append((parsed.visit_date, item))
    enriched.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in enriched[:latest]]


def is_supported_image_filename(filename: str) -> bool:
    lowered = filename.lower()
    return any(lowered.endswith(ext) for ext in SUPPORTED_IMAGE_EXTENSIONS)


def collect_images_recursive(drive_client: DriveClientProtocol, folder_id: str) -> list[ImageEntry]:
    stack = [folder_id]
    collected: list[ImageEntry] = []

    while stack:
        current_folder_id = stack.pop()
        for entry in drive_client.list_children(current_folder_id):
            entry_id = entry.get("id", "").strip()
            entry_name = entry.get("name", "").strip()
            mime_type = entry.get("mimeType", "").strip()
            if not entry_id or not entry_name or not mime_type:
                continue

            if mime_type == DRIVE_FOLDER_MIME_TYPE:
                stack.append(entry_id)
                continue

            if is_supported_image_filename(entry_name):
                collected.append(
                    ImageEntry(file_id=entry_id, name=entry_name, mime_type=mime_type)
                )

    collected.sort(key=lambda item: item.name.lower())
    return collected


def build_manifest(
    source_folder_id: str,
    source_folder_name: str,
    images: list[ImageEntry],
) -> Manifest:
    parsed = parse_source_folder_name(source_folder_name)
    return Manifest(
        source_folder_id=source_folder_id,
        source_folder_name=source_folder_name,
        visit_date=parsed.visit_date,
        restaurant_name=parsed.restaurant_name,
        images=images,
    )
