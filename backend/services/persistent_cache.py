"""Small, versioned JSON cache for restart-safe analysis artifacts."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()


def canonical_cache_key(namespace: str, components: dict[str, Any]) -> str:
    payload = json.dumps(components, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{namespace}-v1-{digest}"


def _path(namespace: str, key: str) -> Path:
    from config import settings

    safe_namespace = "".join(ch for ch in namespace if ch.isalnum() or ch in "-_")
    return settings.analysis_cache_dir / safe_namespace / f"{key}.json"


def load_json(namespace: str, key: str) -> dict[str, Any] | None:
    from config import settings

    if not settings.enable_persistent_analysis_cache:
        return None
    path = _path(namespace, key)
    try:
        with _LOCK:
            payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if payload.get("cache_schema") == 1 else None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def save_json(namespace: str, key: str, payload: dict[str, Any]) -> None:
    from config import settings

    if not settings.enable_persistent_analysis_cache:
        return
    path = _path(namespace, key)
    body = {"cache_schema": 1, **payload}
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
            temporary.replace(path)
            entries = sorted(
                path.parent.glob("*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for stale in entries[max(1, settings.persistent_analysis_cache_max_entries):]:
                stale.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError):
        return


def clear_namespace(namespace: str) -> None:
    directory = _path(namespace, "placeholder").parent
    try:
        with _LOCK:
            for path in directory.glob("*.json"):
                path.unlink(missing_ok=True)
    except OSError:
        return
