#!/usr/bin/env python3
"""Validate the local MinerU pipeline model bundle used by the image."""

from __future__ import annotations

import json
import os
from pathlib import Path


REQUIRED_PIPELINE_PATHS = (
    "models/Layout/PP-DocLayoutV2",
    "models/MFR/unimernet_hf_small_2503",
    "models/OCR/paddleocr_torch",
    "models/TabRec/SlanetPlus/slanet-plus.onnx",
    "models/TabRec/UnetStructure/unet.onnx",
    "models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx",
    "models/MFR/pp_formulanet_plus_m",
)


def _config_path() -> Path:
    configured = Path(os.getenv("MINERU_TOOLS_CONFIG_JSON", "mineru.json"))
    return configured if configured.is_absolute() else Path.home() / configured


def _has_non_empty_content(path: Path) -> bool:
    if path.is_file():
        return path.stat().st_size > 0
    if path.is_dir():
        return any(
            child.is_file() and child.stat().st_size > 0
            for child in path.rglob("*")
        )
    return False


def main() -> int:
    model_source = os.getenv("MINERU_MODEL_SOURCE")
    if model_source != "local":
        raise SystemExit(
            f"MINERU_MODEL_SOURCE must be 'local', got {model_source!r}"
        )

    config_path = _config_path()
    if not config_path.is_file():
        raise SystemExit(f"MinerU config is missing: {config_path}")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        configured_root = config["models-dir"]["pipeline"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SystemExit(f"Invalid MinerU config {config_path}: {exc}") from exc

    if not isinstance(configured_root, str) or not configured_root:
        raise SystemExit("MinerU pipeline model root is not configured")

    model_root = Path(configured_root)
    if not model_root.is_absolute():
        raise SystemExit(f"MinerU pipeline model root must be absolute: {model_root}")

    missing_or_empty = [
        relative_path
        for relative_path in REQUIRED_PIPELINE_PATHS
        if not _has_non_empty_content(model_root / relative_path)
    ]
    if missing_or_empty:
        raise SystemExit(
            "MinerU pipeline models are missing or empty under "
            f"{model_root}: {', '.join(missing_or_empty)}"
        )

    print(
        f"MinerU local model bundle ready: {model_root} "
        f"({len(REQUIRED_PIPELINE_PATHS)} required paths)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
