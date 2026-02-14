"""Runtime config loader for pipeline execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_runtime_config(config_file: str | None) -> dict[str, Any]:
    if not config_file:
        return {}
    path = Path(config_file)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_file}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("config file must contain a JSON object")
    return payload


def value_from_sources(
    *,
    cli_value: Any,
    config: dict[str, Any],
    key: str,
    default: Any = None,
) -> Any:
    if cli_value is not None:
        return cli_value
    if key in config:
        return config[key]
    return default

