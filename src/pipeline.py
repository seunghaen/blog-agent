"""CLI entrypoint and orchestration skeleton for blog pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from mimetypes import guess_type
from pathlib import Path
from typing import Sequence

from .rules import assert_stage
from .scan_folders import (
    DRIVE_FOLDER_MIME_TYPE,
    Manifest,
    build_manifest,
    collect_images_recursive,
    list_source_folders,
    select_latest_source_folders,
)


@dataclass(frozen=True)
class PipelineConfig:
    input_root_id: str
    output_root_id: str
    latest: int
    stage: int
    write_intermediates: bool


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.pipeline",
        description="Google Drive based restaurant blog pipeline (Stage 1~4).",
    )
    parser.add_argument(
        "--input-root-id",
        required=True,
        help="Drive folder id for RestaurantReviews",
    )
    parser.add_argument(
        "--output-root-id",
        required=True,
        help="Drive folder id for RestaurantReviewsOutputs",
    )
    parser.add_argument(
        "--latest",
        type=int,
        default=1,
        help="How many latest source folders to target (default: 1)",
    )
    parser.add_argument(
        "--stage",
        type=int,
        default=4,
        help="Maximum stage to execute (1~4, default: 4)",
    )
    parser.add_argument(
        "--write-intermediates",
        action="store_true",
        help="Write Stage 1~3 intermediate artifacts for debugging",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> PipelineConfig:
    args = build_parser().parse_args(argv)
    if args.latest < 1:
        raise ValueError("--latest must be >= 1")
    assert_stage(args.stage)

    return PipelineConfig(
        input_root_id=args.input_root_id,
        output_root_id=args.output_root_id,
        latest=args.latest,
        stage=args.stage,
        write_intermediates=args.write_intermediates,
    )


def run_pipeline(config: PipelineConfig) -> int:
    drive_client = LocalDriveClient()
    manifests = _run_stage_1(config=config, drive_client=drive_client)
    print(f"Stage 1 completed. selected_folders={len(manifests)}")
    if config.stage >= 2:
        print("Stage 2 is not implemented yet.")
    if config.stage >= 3:
        print("Stage 3 is not implemented yet.")
    if config.stage >= 4:
        print("Stage 4 is not implemented yet.")
    return 0


def _run_stage_1(config: PipelineConfig, drive_client: LocalDriveClient) -> list[Manifest]:
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
        _write_stage_1_outputs(config=config, manifests=manifests)
    return manifests


def _write_stage_1_outputs(config: PipelineConfig, manifests: list[Manifest]) -> None:
    output_root = Path(config.output_root_id)
    output_root.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        folder_dir = output_root / manifest.source_folder_name
        folder_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = folder_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def main(argv: Sequence[str] | None = None) -> int:
    config = parse_args(argv)
    return run_pipeline(config)


if __name__ == "__main__":
    raise SystemExit(main())
