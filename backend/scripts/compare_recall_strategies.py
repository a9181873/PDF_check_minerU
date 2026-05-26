"""Run MinerU forced-OCR recall A/B over EDM PDF pairs.

This intentionally compares only the recall algorithm output:
IMAGE_TEXT_RECALL_STRATEGY=alignment versus heuristic. It does not add rules to
the legacy heuristic; it exists so real EDM samples can decide whether alignment
is safer before changing defaults.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from models.diff_models import DiffItem
from services.diff_service import diff_aligned_paragraphs, diff_positioned_paragraphs
from services.parser_service import parse_image_pdf_via_mineru_ocr


def _clip(value: str | None, limit: int = 160) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "..."


def _page(item: DiffItem) -> int | None:
    box = item.old_bbox or item.new_bbox
    return box.page if box else None


def _item_to_dict(item: DiffItem) -> dict[str, Any]:
    return {
        "type": item.diff_type.value,
        "page": _page(item),
        "old": _clip(item.old_value),
        "new": _clip(item.new_value),
        "context": item.context,
        "confidence": item.confidence,
    }


def _case_key(path: Path, root: Path) -> str:
    parent = path.parent
    if parent != root:
        return str(parent.relative_to(root))

    stem = path.stem
    for marker in ("_商品DM", "_DM", "_背面"):
        if marker in stem:
            return stem.split(marker, 1)[0]
    return stem.rsplit("_", 1)[0]


def discover_pairs(root: Path) -> list[tuple[str, Path, Path]]:
    groups: dict[str, list[Path]] = {}
    for pdf in sorted(root.rglob("*.pdf")):
        groups.setdefault(_case_key(pdf, root), []).append(pdf)

    pairs: list[tuple[str, Path, Path]] = []
    for case, files in sorted(groups.items()):
        if len(files) != 2:
            continue
        ordered = sorted(files, key=lambda p: p.name)
        pairs.append((case, ordered[0], ordered[1]))
    return pairs


def compare_case(case: str, old_path: Path, new_path: Path, strategies: list[str]) -> dict[str, Any]:
    old_ocr = parse_image_pdf_via_mineru_ocr(str(old_path))
    new_ocr = parse_image_pdf_via_mineru_ocr(str(new_path))

    result: dict[str, Any] = {
        "case": case,
        "old": str(old_path),
        "new": str(new_path),
        "old_pages": old_ocr.pages,
        "new_pages": new_ocr.pages,
        "old_paragraphs": len(old_ocr.paragraphs),
        "new_paragraphs": len(new_ocr.paragraphs),
        "strategies": {},
    }

    for strategy in strategies:
        settings.image_text_recall_strategy = strategy
        if strategy == "alignment":
            items = diff_aligned_paragraphs(old_ocr.paragraphs, new_ocr.paragraphs)
        else:
            items = diff_positioned_paragraphs(old_ocr.paragraphs, new_ocr.paragraphs)
        counts = Counter(item.diff_type.value for item in items)
        result["strategies"][strategy] = {
            "total": len(items),
            "counts": dict(sorted(counts.items())),
            "items": [_item_to_dict(item) for item in items],
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dm-root", default=os.getenv("DM_ROOT", "/dm"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--strategies", nargs="+", default=["alignment", "heuristic"])
    args = parser.parse_args()

    root = Path(args.dm_root)
    if not root.exists():
        raise FileNotFoundError(f"DM root not found: {root}")

    settings.enable_image_text_recall = True
    strategies = [s.strip().lower() for s in args.strategies]
    if any(s not in {"alignment", "heuristic"} for s in strategies):
        raise ValueError("--strategies accepts only alignment and heuristic")

    pairs = discover_pairs(root)
    if args.cases:
        wanted = set(args.cases)
        pairs = [pair for pair in pairs if pair[0] in wanted]
    if args.limit > 0:
        pairs = pairs[: args.limit]

    results = []
    for case, old_path, new_path in pairs:
        try:
            case_result = compare_case(case, old_path, new_path, strategies)
        except Exception as exc:
            case_result = {
                "case": case,
                "old": str(old_path),
                "new": str(new_path),
                "error": f"{type(exc).__name__}: {exc}",
            }
        results.append(case_result)

        print(f"\n## {case}")
        if "error" in case_result:
            print(f"ERROR {case_result['error']}")
            continue
        for strategy in strategies:
            summary = case_result["strategies"][strategy]
            print(f"{strategy}: total={summary['total']} counts={summary['counts']}")

    payload = {"dm_root": str(root), "cases": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
