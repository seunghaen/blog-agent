"""CLI entrypoint and orchestration skeleton for blog pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import json
from mimetypes import guess_type
import os
from pathlib import Path
import re
from typing import Any, Protocol, Sequence

from .places_client import (
    GooglePlacesProvider,
    PlacesClient,
    PlacesProviderProtocol,
    RestaurantInfo,
)
from .rules import RulesReport, assert_stage, validate_html_document
from .runtime_config import load_runtime_config, value_from_sources
from .scan_folders import (
    DRIVE_FOLDER_MIME_TYPE,
    Manifest,
    build_manifest,
    collect_images_recursive,
    list_source_folders,
    select_latest_source_folders,
)
from .vision_client import (
    GeminiVisionProvider,
    VisionClient,
    VisionImageResult,
    VisionProviderProtocol,
)
from .writer import render_review_html
from .prompts import PromptSet, load_prompts

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


@dataclass(frozen=True)
class PipelineConfig:
    input_root_id: str
    output_root_id: str
    latest: int
    stage: int
    write_intermediates: bool
    places_data: str | None
    vision_data: str | None
    places_api_key: str | None
    vision_api_key: str | None
    vision_model: str
    prompt_file: str | None
    storage_mode: str
    google_auth_mode: str
    google_credentials_file: str | None
    google_oauth_token_file: str | None


class StorageClientProtocol(Protocol):
    def list_children(self, folder_id: str) -> list[dict[str, str]]:
        """Return child file/folder entries."""

    def ensure_folder(self, parent_id: str, folder_name: str) -> str:
        """Ensure a folder under parent and return its id/path."""

    def upload_text(self, parent_id: str, file_name: str, text: str, mime_type: str) -> None:
        """Upload or overwrite a text file in parent."""

    def download_bytes(self, file_id: str) -> bytes:
        """Download bytes for a file id/path."""


class LocalDriveClient:
    """Local filesystem adapter used as a Drive client placeholder."""

    def list_children(self, folder_id: str) -> list[dict[str, str]]:
        folder_path = Path(folder_id)
        if not folder_path.exists() or not folder_path.is_dir():
            raise FileNotFoundError(f"Folder not found: {folder_id}")

        children: list[dict[str, str]] = []
        for child in folder_path.iterdir():
            if child.is_dir():
                mime_type = DRIVE_FOLDER_MIME_TYPE
            else:
                mime_type = guess_type(child.name)[0] or "application/octet-stream"

            children.append(
                {
                    "id": str(child),
                    "name": child.name,
                    "mimeType": mime_type,
                }
            )
        return children

    def ensure_folder(self, parent_id: str, folder_name: str) -> str:
        folder_path = Path(parent_id) / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        return str(folder_path)

    def upload_text(self, parent_id: str, file_name: str, text: str, mime_type: str) -> None:
        del mime_type
        file_path = Path(parent_id) / file_name
        file_path.write_text(text, encoding="utf-8")

    def download_bytes(self, file_id: str) -> bytes:
        return Path(file_id).read_bytes()


class GoogleDriveClient:
    """Google Drive API adapter."""

    def __init__(self, service: Any) -> None:
        self._service = service

    @classmethod
    def from_credentials(
        cls,
        auth_mode: str,
        credentials_file: str,
        oauth_token_file: str | None = None,
    ) -> "GoogleDriveClient":
        if auth_mode == "service_account":
            try:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError(
                    "Google Drive dependencies missing. Install google-api-python-client and google-auth."
                ) from exc

            credentials = service_account.Credentials.from_service_account_file(
                credentials_file,
                scopes=DRIVE_SCOPES,
            )
            service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            return cls(service=service)

        if auth_mode == "oauth":
            try:
                from google.auth.transport.requests import Request
                from google.oauth2.credentials import Credentials
                from google_auth_oauthlib.flow import InstalledAppFlow
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise RuntimeError(
                    "Google OAuth dependencies missing. Install google-api-python-client, google-auth-oauthlib."
                ) from exc

            token_file = oauth_token_file or ".cache/google_oauth_token.json"
            token_path = Path(token_file)
            token_path.parent.mkdir(parents=True, exist_ok=True)

            creds: Credentials | None = None
            if token_path.exists():
                creds = Credentials.from_authorized_user_file(str(token_path), DRIVE_SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(credentials_file, DRIVE_SCOPES)
                    creds = flow.run_console()
                token_path.write_text(creds.to_json(), encoding="utf-8")

            service = build("drive", "v3", credentials=creds, cache_discovery=False)
            return cls(service=service)

        raise ValueError("google auth mode must be one of: service_account, oauth")

    def list_children(self, folder_id: str) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        page_token: str | None = None

        query = f"'{_escape_drive_query(folder_id)}' in parents and trashed=false"
        while True:
            response = (
                self._service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id,name,mimeType)",
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return [
            {"id": str(item["id"]), "name": str(item["name"]), "mimeType": str(item["mimeType"])}
            for item in files
            if item.get("id") and item.get("name") and item.get("mimeType")
        ]

    def ensure_folder(self, parent_id: str, folder_name: str) -> str:
        existing = self._find_child_id(
            parent_id=parent_id,
            name=folder_name,
            mime_type=DRIVE_FOLDER_MIME_TYPE,
        )
        if existing:
            return existing

        metadata = {
            "name": folder_name,
            "mimeType": DRIVE_FOLDER_MIME_TYPE,
            "parents": [parent_id],
        }
        response = (
            self._service.files()
            .create(
                body=metadata,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        return str(response["id"])

    def upload_text(self, parent_id: str, file_name: str, text: str, mime_type: str) -> None:
        try:
            from googleapiclient.http import MediaIoBaseUpload
        except ImportError as exc:
            raise RuntimeError(
                "Google Drive dependencies missing. Install google-api-python-client."
            ) from exc

        file_id = self._find_child_id(parent_id=parent_id, name=file_name, mime_type=None)
        media = MediaIoBaseUpload(
            io.BytesIO(text.encode("utf-8")),
            mimetype=mime_type,
            resumable=False,
        )

        if file_id:
            (
                self._service.files()
                .update(
                    fileId=file_id,
                    media_body=media,
                    supportsAllDrives=True,
                )
                .execute()
            )
            return

        metadata = {"name": file_name, "parents": [parent_id]}
        (
            self._service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )

    def download_bytes(self, file_id: str) -> bytes:
        try:
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError as exc:
            raise RuntimeError(
                "Google Drive dependencies missing. Install google-api-python-client."
            ) from exc

        request = self._service.files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def _find_child_id(self, parent_id: str, name: str, mime_type: str | None) -> str | None:
        escaped_name = _escape_drive_query(name)
        query = (
            f"'{_escape_drive_query(parent_id)}' in parents and "
            f"name='{escaped_name}' and trashed=false"
        )
        if mime_type:
            query += f" and mimeType='{_escape_drive_query(mime_type)}'"

        response = (
            self._service.files()
            .list(
                q=query,
                fields="files(id)",
                pageSize=1,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files = response.get("files", [])
        if not files:
            return None
        return str(files[0]["id"])


class JsonPlacesProvider(PlacesProviderProtocol):
    """JSON-backed provider for local development and tests."""

    def __init__(self, payload: dict[str, Any]) -> None:
        restaurants = payload.get("restaurants", payload)
        if not isinstance(restaurants, dict):
            raise ValueError("places data must be a mapping")

        self._by_name: dict[str, dict[str, Any]] = {}
        self._by_place_id: dict[str, dict[str, Any]] = {}
        for restaurant_name, details in restaurants.items():
            if not isinstance(details, dict):
                continue
            place_id = str(details.get("place_id", "")).strip()
            if not place_id:
                continue
            key = str(restaurant_name).strip().lower()
            if not key:
                continue
            self._by_name[key] = details
            self._by_place_id[place_id] = details

    def search_place(self, restaurant_name: str) -> dict[str, Any] | None:
        details = self._by_name.get(restaurant_name.strip().lower())
        if not details:
            return None
        return {"place_id": details["place_id"]}

    def get_place_details(self, place_id: str) -> dict[str, Any] | None:
        return self._by_place_id.get(place_id)


class JsonVisionProvider(VisionProviderProtocol):
    """JSON-backed provider for local development and tests."""

    def __init__(self, payload: dict[str, Any]) -> None:
        images = payload.get("images", payload)
        if not isinstance(images, dict):
            raise ValueError("vision data must be a mapping")
        self._images = images

    def analyze_image(
        self,
        file_id: str,
        image_name: str,
        mime_type: str | None = None,
        image_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        del mime_type, image_bytes
        by_file_id = self._images.get(file_id)
        if isinstance(by_file_id, dict):
            return by_file_id

        by_name = self._images.get(image_name)
        if isinstance(by_name, dict):
            return by_name

        by_name_lower = self._images.get(image_name.lower())
        if isinstance(by_name_lower, dict):
            return by_name_lower

        return {
            "scene_type": "other",
            "observations": [],
            "food_guess": [],
            "ambience_hints": [],
            "bloggable_details": [],
            "warnings": [f"no vision data for {image_name}"],
        }


EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "]+"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.pipeline",
        description="Google Drive based restaurant blog pipeline (Stage 1~4).",
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help="Optional JSON config file for runtime settings",
    )
    parser.add_argument(
        "--input-root-id",
        default=None,
        help="Drive folder id for RestaurantReviews",
    )
    parser.add_argument(
        "--output-root-id",
        default=None,
        help="Drive folder id for RestaurantReviewsOutputs",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=None,
        help="How many latest source folders to target (default: 1)",
    )
    parser.add_argument(
        "--stage",
        type=int,
        default=None,
        help="Maximum stage to execute (1~4, default: 4)",
    )
    parser.add_argument(
        "--write-intermediates",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Write Stage 1~3 intermediate artifacts for debugging",
    )
    parser.add_argument(
        "--places-data",
        default=None,
        help="Optional JSON file path for local Stage 2 place lookup",
    )
    parser.add_argument(
        "--vision-data",
        default=None,
        help="Optional JSON file path for local Stage 3 vision lookup",
    )
    parser.add_argument(
        "--places-api-key",
        default=None,
        help="Google Places API key (or GOOGLE_PLACES_API_KEY env)",
    )
    parser.add_argument(
        "--vision-api-key",
        default=None,
        help="Gemini API key (or GEMINI_API_KEY / GOOGLE_API_KEY env)",
    )
    parser.add_argument(
        "--vision-model",
        default=None,
        help="Gemini model name for vision analysis",
    )
    parser.add_argument(
        "--prompt-file",
        default=None,
        help="Optional JSON file for blog/vision prompt templates",
    )
    parser.add_argument(
        "--storage-mode",
        choices=("local", "drive"),
        default=None,
        help="Storage backend mode (default: local)",
    )
    parser.add_argument(
        "--google-auth-mode",
        choices=("service_account", "oauth"),
        default=None,
        help="Google auth mode for --storage-mode drive",
    )
    parser.add_argument(
        "--google-credentials-file",
        default=None,
        help="Path to Google service-account key file or OAuth client secrets",
    )
    parser.add_argument(
        "--google-oauth-token-file",
        default=None,
        help="Path to cached OAuth token file for drive mode",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> PipelineConfig:
    args = build_parser().parse_args(argv)
    file_config = load_runtime_config(args.config_file)

    input_root_id = value_from_sources(
        cli_value=args.input_root_id,
        config=file_config,
        key="input_root_id",
    )
    output_root_id = value_from_sources(
        cli_value=args.output_root_id,
        config=file_config,
        key="output_root_id",
    )
    latest = int(
        value_from_sources(
            cli_value=args.latest,
            config=file_config,
            key="latest",
            default=1,
        )
    )
    stage = int(
        value_from_sources(
            cli_value=args.stage,
            config=file_config,
            key="stage",
            default=4,
        )
    )
    write_intermediates = bool(
        value_from_sources(
            cli_value=args.write_intermediates,
            config=file_config,
            key="write_intermediates",
            default=False,
        )
    )
    places_data = value_from_sources(
        cli_value=args.places_data,
        config=file_config,
        key="places_data",
        default=None,
    )
    vision_data = value_from_sources(
        cli_value=args.vision_data,
        config=file_config,
        key="vision_data",
        default=None,
    )
    places_api_key = value_from_sources(
        cli_value=args.places_api_key,
        config=file_config,
        key="places_api_key",
        default=os.getenv("GOOGLE_PLACES_API_KEY"),
    )
    vision_api_key = value_from_sources(
        cli_value=args.vision_api_key,
        config=file_config,
        key="vision_api_key",
        default=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
    )
    vision_model = str(
        value_from_sources(
            cli_value=args.vision_model,
            config=file_config,
            key="vision_model",
            default="gemini-1.5-flash",
        )
    )
    prompt_file = value_from_sources(
        cli_value=args.prompt_file,
        config=file_config,
        key="prompt_file",
        default=None,
    )
    storage_mode = str(
        value_from_sources(
            cli_value=args.storage_mode,
            config=file_config,
            key="storage_mode",
            default="local",
        )
    )
    google_auth_mode = str(
        value_from_sources(
            cli_value=args.google_auth_mode,
            config=file_config,
            key="google_auth_mode",
            default="service_account",
        )
    )
    google_credentials_file = value_from_sources(
        cli_value=args.google_credentials_file,
        config=file_config,
        key="google_credentials_file",
        default=os.getenv("GOOGLE_CREDENTIALS_FILE")
        or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"),
    )
    google_oauth_token_file = value_from_sources(
        cli_value=args.google_oauth_token_file,
        config=file_config,
        key="google_oauth_token_file",
        default=".cache/google_oauth_token.json",
    )

    if not input_root_id:
        raise ValueError("input_root_id is required (CLI or config file)")
    if not output_root_id:
        raise ValueError("output_root_id is required (CLI or config file)")
    if latest < 1:
        raise ValueError("--latest must be >= 1")
    assert_stage(stage)
    if storage_mode not in {"local", "drive"}:
        raise ValueError("storage_mode must be one of: local, drive")
    if google_auth_mode not in {"service_account", "oauth"}:
        raise ValueError("google_auth_mode must be one of: service_account, oauth")

    if storage_mode == "drive":
        if not google_credentials_file:
            raise ValueError(
                "Drive mode requires --google-credentials-file "
                "(or GOOGLE_CREDENTIALS_FILE / GOOGLE_APPLICATION_CREDENTIALS)."
            )

    return PipelineConfig(
        input_root_id=str(input_root_id),
        output_root_id=str(output_root_id),
        latest=latest,
        stage=stage,
        write_intermediates=write_intermediates,
        places_data=str(places_data) if places_data else None,
        vision_data=str(vision_data) if vision_data else None,
        places_api_key=str(places_api_key) if places_api_key else None,
        vision_api_key=str(vision_api_key) if vision_api_key else None,
        vision_model=vision_model,
        prompt_file=str(prompt_file) if prompt_file else None,
        storage_mode=storage_mode,
        google_auth_mode=google_auth_mode,
        google_credentials_file=str(google_credentials_file) if google_credentials_file else None,
        google_oauth_token_file=str(google_oauth_token_file) if google_oauth_token_file else None,
    )


def run_pipeline(config: PipelineConfig) -> int:
    storage_client = _build_storage_client(config)
    prompts = load_prompts(config.prompt_file)
    manifests = _run_stage_1(config=config, drive_client=storage_client)
    print(f"Stage 1 completed. selected_folders={len(manifests)}")

    restaurant_infos: dict[str, RestaurantInfo] = {}
    if config.stage >= 2:
        places_client = PlacesClient(provider=_build_places_provider(config))
        restaurant_infos = _run_stage_2(
            config=config,
            manifests=manifests,
            places_client=places_client,
            storage_client=storage_client,
        )
        found_count = sum(1 for info in restaurant_infos.values() if info.found)
        print(
            f"Stage 2 completed. restaurant_infos={len(restaurant_infos)} "
            f"found={found_count}"
        )

    vision_results: dict[str, list[VisionImageResult]] = {}
    if config.stage >= 3:
        vision_client = VisionClient(provider=_build_vision_provider(config, prompts))
        vision_results = _run_stage_3(
            config=config,
            manifests=manifests,
            vision_client=vision_client,
            storage_client=storage_client,
        )
        image_count = sum(len(results) for results in vision_results.values())
        print(f"Stage 3 completed. vision_images={image_count}")

    if config.stage >= 4:
        reports = _run_stage_4(
            config=config,
            manifests=manifests,
            restaurant_infos=restaurant_infos,
            vision_results=vision_results,
            storage_client=storage_client,
            prompts=prompts,
        )
        passed_count = sum(1 for report in reports.values() if report.passed)
        print(
            f"Stage 4 completed. outputs={len(reports)} "
            f"rules_passed={passed_count}/{len(reports)}"
        )
        if passed_count != len(reports):
            return 1
    return 0


def _build_storage_client(config: PipelineConfig) -> StorageClientProtocol:
    if config.storage_mode == "local":
        return LocalDriveClient()
    if config.storage_mode == "drive":
        if not config.google_credentials_file:
            raise ValueError("google credentials file is required for drive mode")
        return GoogleDriveClient.from_credentials(
            auth_mode=config.google_auth_mode,
            credentials_file=config.google_credentials_file,
            oauth_token_file=config.google_oauth_token_file,
        )
    raise ValueError("storage mode must be one of: local, drive")


def _run_stage_1(config: PipelineConfig, drive_client: StorageClientProtocol) -> list[Manifest]:
    source_folders = list_source_folders(
        drive_client=drive_client,
        input_root_id=config.input_root_id,
    )
    if not source_folders:
        raise RuntimeError("No valid source folders found under input root.")

    selected = select_latest_source_folders(source_folders, latest=config.latest)
    manifests: list[Manifest] = []
    for folder in selected:
        images = collect_images_recursive(drive_client, folder.folder_id)
        if not images:
            raise RuntimeError(f"No supported image files found in {folder.folder_name}")

        manifest = build_manifest(
            source_folder_id=folder.folder_id,
            source_folder_name=folder.folder_name,
            images=images,
        )
        manifests.append(manifest)

    should_write_manifest = config.stage == 1 or config.write_intermediates
    if should_write_manifest:
        _write_stage_1_outputs(
            config=config,
            manifests=manifests,
            storage_client=drive_client,
        )
    return manifests


def _write_stage_1_outputs(
    config: PipelineConfig,
    manifests: list[Manifest],
    storage_client: StorageClientProtocol,
) -> None:
    for manifest in manifests:
        folder_id = storage_client.ensure_folder(
            parent_id=config.output_root_id,
            folder_name=manifest.source_folder_name,
        )
        storage_client.upload_text(
            parent_id=folder_id,
            file_name="manifest.json",
            text=json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            mime_type="application/json",
        )


def _run_stage_2(
    config: PipelineConfig,
    manifests: list[Manifest],
    places_client: PlacesClient,
    storage_client: StorageClientProtocol,
) -> dict[str, RestaurantInfo]:
    by_folder: dict[str, RestaurantInfo] = {}
    for manifest in manifests:
        restaurant_info = places_client.fetch_restaurant_info(
            restaurant_name=manifest.restaurant_name,
            cutoff_days=60,
        )
        by_folder[manifest.source_folder_name] = restaurant_info

    should_write_restaurant = config.stage == 2 or config.write_intermediates
    if should_write_restaurant:
        _write_stage_2_outputs(
            config=config,
            by_folder=by_folder,
            storage_client=storage_client,
        )
    return by_folder


def _write_stage_2_outputs(
    config: PipelineConfig,
    by_folder: dict[str, RestaurantInfo],
    storage_client: StorageClientProtocol,
) -> None:
    for source_folder_name, restaurant_info in by_folder.items():
        folder_id = storage_client.ensure_folder(
            parent_id=config.output_root_id,
            folder_name=source_folder_name,
        )
        storage_client.upload_text(
            parent_id=folder_id,
            file_name="restaurant.json",
            text=json.dumps(restaurant_info.to_dict(), ensure_ascii=False, indent=2),
            mime_type="application/json",
        )


def _build_places_provider(config: PipelineConfig) -> PlacesProviderProtocol | None:
    if config.places_api_key:
        return GooglePlacesProvider(api_key=config.places_api_key)

    if not config.places_data:
        return None
    places_data_path = Path(config.places_data)
    if not places_data_path.exists() or not places_data_path.is_file():
        raise FileNotFoundError(f"Places data file not found: {config.places_data}")

    payload = json.loads(places_data_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("places data file must contain a JSON object")
    return JsonPlacesProvider(payload)


def _run_stage_3(
    config: PipelineConfig,
    manifests: list[Manifest],
    vision_client: VisionClient,
    storage_client: StorageClientProtocol,
) -> dict[str, list[VisionImageResult]]:
    by_folder: dict[str, list[VisionImageResult]] = {}
    for manifest in manifests:
        results: list[VisionImageResult] = []
        for image in manifest.images:
            image_bytes: bytes | None = None
            try:
                image_bytes = storage_client.download_bytes(image.file_id)
            except Exception:
                image_bytes = None
            results.append(
                vision_client.analyze(
                    file_id=image.file_id,
                    image_name=image.name,
                    mime_type=image.mime_type,
                    image_bytes=image_bytes,
                )
            )
        by_folder[manifest.source_folder_name] = results

    should_write_vision = config.stage == 3 or config.write_intermediates
    if should_write_vision:
        _write_stage_3_outputs(
            config=config,
            by_folder=by_folder,
            storage_client=storage_client,
        )
    return by_folder


def _write_stage_3_outputs(
    config: PipelineConfig,
    by_folder: dict[str, list[VisionImageResult]],
    storage_client: StorageClientProtocol,
) -> None:
    for source_folder_name, results in by_folder.items():
        folder_id = storage_client.ensure_folder(
            parent_id=config.output_root_id,
            folder_name=source_folder_name,
        )
        payload = {"images": [result.to_dict() for result in results]}
        storage_client.upload_text(
            parent_id=folder_id,
            file_name="vision.json",
            text=json.dumps(payload, ensure_ascii=False, indent=2),
            mime_type="application/json",
        )


def _build_vision_provider(config: PipelineConfig, prompts: PromptSet) -> VisionProviderProtocol | None:
    if config.vision_api_key:
        return GeminiVisionProvider(
            api_key=config.vision_api_key,
            model=config.vision_model,
            prompt=prompts.vision_prompt,
        )

    if not config.vision_data:
        return None
    vision_data_path = Path(config.vision_data)
    if not vision_data_path.exists() or not vision_data_path.is_file():
        raise FileNotFoundError(f"Vision data file not found: {config.vision_data}")

    payload = json.loads(vision_data_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("vision data file must contain a JSON object")
    return JsonVisionProvider(payload)


def _run_stage_4(
    config: PipelineConfig,
    manifests: list[Manifest],
    restaurant_infos: dict[str, RestaurantInfo],
    vision_results: dict[str, list[VisionImageResult]],
    storage_client: StorageClientProtocol,
    prompts: PromptSet,
) -> dict[str, RulesReport]:
    reports: dict[str, RulesReport] = {}

    for manifest in manifests:
        folder_name = manifest.source_folder_name
        restaurant_info = restaurant_infos.get(
            folder_name,
            RestaurantInfo(found=False, recent_reviews_cutoff_days=60),
        )
        results = vision_results.get(folder_name, [])

        html_text = _build_review_html(
            manifest=manifest,
            restaurant_info=restaurant_info,
            vision_results=results,
            prompts=prompts,
        )
        report = validate_html_document(
            html_text=html_text,
            recent_review_count=len(restaurant_info.recent_reviews),
        )
        reports[folder_name] = report

        folder_id = storage_client.ensure_folder(
            parent_id=config.output_root_id,
            folder_name=folder_name,
        )
        storage_client.upload_text(
            parent_id=folder_id,
            file_name="review.html",
            text=html_text,
            mime_type="text/html",
        )
        storage_client.upload_text(
            parent_id=folder_id,
            file_name="rules_report.json",
            text=json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            mime_type="application/json",
        )

    return reports


def _build_review_html(
    manifest: Manifest,
    restaurant_info: RestaurantInfo,
    vision_results: list[VisionImageResult],
    prompts: PromptSet,
) -> str:
    info_lines = _build_info_lines(restaurant_info, prompts=prompts)
    paragraphs = _build_paragraphs(
        manifest,
        restaurant_info,
        vision_results,
        prompts=prompts,
    )
    return render_review_html(
        title=_format_template(
            prompts.title_template,
            restaurant_name=manifest.restaurant_name,
        ),
        restaurant_name=manifest.restaurant_name,
        visit_date=manifest.visit_date,
        paragraphs=paragraphs,
        info_lines=info_lines,
    )


def _build_info_lines(restaurant_info: RestaurantInfo, prompts: PromptSet) -> list[str]:
    lines: list[str] = []
    if restaurant_info.found:
        if restaurant_info.address:
            lines.append(f"주소: {restaurant_info.address}")
        if restaurant_info.opening_hours:
            lines.append(f"영업시간: {', '.join(restaurant_info.opening_hours[:2])}")
        if restaurant_info.rating is not None:
            rating_line = f"평점 정보: {restaurant_info.rating}"
            if restaurant_info.user_ratings_total is not None:
                rating_line += f" ({restaurant_info.user_ratings_total}건 기준)"
            lines.append(rating_line)
        if restaurant_info.website:
            lines.append(f"웹사이트: {restaurant_info.website}")
        if restaurant_info.maps_url:
            lines.append(f"지도: {restaurant_info.maps_url}")
    else:
        lines.append(prompts.missing_info_line)

    return [_sanitize_text(line) for line in lines if line.strip()]


def _build_paragraphs(
    manifest: Manifest,
    restaurant_info: RestaurantInfo,
    vision_results: list[VisionImageResult],
    prompts: PromptSet,
) -> list[str]:
    paragraphs: list[str] = []
    paragraphs.append(
        _format_template(
            prompts.intro_template,
            visit_date=manifest.visit_date,
            image_count=len(manifest.images),
            restaurant_name=manifest.restaurant_name,
        )
    )

    scene_counter: dict[str, int] = {}
    observations: list[str] = []
    food_guesses: list[str] = []
    for result in vision_results:
        if not result.analysis:
            continue
        scene = result.analysis.scene_type.strip() or "other"
        scene_counter[scene] = scene_counter.get(scene, 0) + 1
        observations.extend(_take_non_empty(result.analysis.observations))
        food_guesses.extend(_take_non_empty(result.analysis.food_guess))

    if scene_counter:
        top_scenes = sorted(scene_counter.items(), key=lambda item: item[1], reverse=True)[:3]
        scene_text = ", ".join(f"{name} {count}장" for name, count in top_scenes)
        paragraphs.append(
            _format_template(
                prompts.scene_summary_template,
                scene_text=scene_text,
                restaurant_name=manifest.restaurant_name,
            )
        )

    if observations:
        unique_observations = _unique_limited(observations, limit=3)
        paragraphs.append(prompts.observations_prefix + " / ".join(unique_observations))

    if food_guesses:
        unique_foods = _unique_limited(food_guesses, limit=3)
        paragraphs.append(prompts.food_guess_prefix + ", ".join(unique_foods))

    if restaurant_info.recent_reviews:
        latest = restaurant_info.recent_reviews[0]
        summary = _trim_text(latest.text, 90)
        if summary:
            paragraphs.append(
                _format_template(
                    prompts.recent_review_template,
                    review_count=len(restaurant_info.recent_reviews),
                    summary=summary,
                    restaurant_name=manifest.restaurant_name,
                )
            )

    if len(paragraphs) == 1:
        paragraphs.append(prompts.fallback_paragraph)

    return [_sanitize_text(item) for item in paragraphs if item.strip()]


def _take_non_empty(values: list[str]) -> list[str]:
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


def _unique_limited(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def _trim_text(value: str, max_len: int) -> str:
    cleaned = value.strip().replace("\n", " ")
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[:max_len].rstrip() + "..."


def _sanitize_text(value: str) -> str:
    sanitized = value.replace("**", "")
    sanitized = sanitized.replace('"', "")
    sanitized = sanitized.replace("<hr", "hr")
    sanitized = sanitized.replace(".gif", ".img")
    sanitized = sanitized.replace("image/gif", "image")
    sanitized = EMOJI_PATTERN.sub("", sanitized)
    return sanitized.strip()


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _format_template(template: str, **kwargs: Any) -> str:
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    return run_pipeline(config)


if __name__ == "__main__":
    raise SystemExit(main())
