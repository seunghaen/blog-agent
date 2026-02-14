from __future__ import annotations

import pytest

from src.scan_folders import (
    SourceFolderEntry,
    parse_source_folder_name,
    select_latest_source_folders,
)


def test_parse_source_folder_name_valid() -> None:
    parsed = parse_source_folder_name("20260214_스시로쿠")
    assert parsed.visit_date == "20260214"
    assert parsed.restaurant_name == "스시로쿠"


@pytest.mark.parametrize(
    "folder_name",
    [
        "2026-02-14_스시로쿠",
        "20260214",
        "not_a_date_식당",
        "20260230_잘못된날짜",
    ],
)
def test_parse_source_folder_name_invalid(folder_name: str) -> None:
    with pytest.raises(ValueError):
        parse_source_folder_name(folder_name)


def test_select_latest_source_folders() -> None:
    source_folders = [
        SourceFolderEntry(folder_id="a", folder_name="20260210_가게A"),
        SourceFolderEntry(folder_id="b", folder_name="20260214_가게B"),
        SourceFolderEntry(folder_id="c", folder_name="20260211_가게C"),
    ]

    selected = select_latest_source_folders(source_folders, latest=2)
    assert [item.folder_name for item in selected] == ["20260214_가게B", "20260211_가게C"]

