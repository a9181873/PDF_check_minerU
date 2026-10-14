#!/usr/bin/env python3
"""Fail readiness unless the MinerU 4.x basic ONNX bundle is complete."""
from __future__ import annotations

import os


def main() -> int:
    from mineru.config import config
    from mineru.model.download import verify_model_repo
    from mineru.model.registry import MINERU_4_MODELS_ONNX

    if os.getenv("MINERU_MODEL_SOURCE") != "local" or config.model.source != "local":
        raise SystemExit("MinerU model source must be local")
    if config.model.small_backend != "onnx":
        raise SystemExit("MinerU small backend must be onnx")
    result = verify_model_repo(MINERU_4_MODELS_ONNX)
    if not result.ready:
        raise SystemExit(f"MinerU ONNX models missing: {', '.join(result.missing_paths)}")
    print(f"MinerU basic ONNX models ready: {MINERU_4_MODELS_ONNX.local_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
