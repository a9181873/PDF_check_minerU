"""Run MinerU forced-OCR recall A/B over EDM PDF pairs.

This intentionally compares only the recall algorithm output:
IMAGE_TEXT_RECALL_STRATEGY=alignment versus heuristic. It does not add rules to
the legacy heuristic; it exists so real EDM samples can decide whether alignment
is safer before changing defaults.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from models.diff_models import BBox, DiffItem
from services.diff_service import diff_aligned_paragraphs, diff_positioned_paragraphs
from services.parser_service import ParsedDocument, ParsedParagraph, parse_image_pdf_via_mineru_ocr
from services.recall_hybrid_service import build_hybrid_recall_candidates, hybrid_candidate_to_dict

_CACHE_VERSION = 1


def _clip(value: str | None, limit: int = 160) -> str | None:
    if value is None:
        return None
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "..."


def _page(item: DiffItem) -> int | None:
    box = item.old_bbox or item.new_bbox
    return box.page if box else None


def _item_to_dict(item: DiffItem, **extra: Any) -> dict[str, Any]:
    payload = {
        "type": item.diff_type.value,
        "page": _page(item),
        "old": _clip(item.old_value),
        "new": _clip(item.new_value),
        "context": item.context,
        "confidence": item.confidence,
    }
    payload.update(extra)
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bbox_to_dict(bbox: BBox | None) -> dict[str, Any] | None:
    return bbox.model_dump() if bbox else None


def _bbox_from_dict(raw: dict[str, Any] | None) -> BBox | None:
    return BBox(**raw) if raw else None


def _paragraph_to_dict(paragraph: ParsedParagraph) -> dict[str, Any]:
    return {
        "text": paragraph.text,
        "bbox": _bbox_to_dict(paragraph.bbox),
        "char_bboxes": [_bbox_to_dict(box) for box in (paragraph.char_bboxes or [])],
        "style": paragraph.style,
    }


def _paragraph_from_dict(raw: dict[str, Any]) -> ParsedParagraph:
    bbox = _bbox_from_dict(raw.get("bbox"))
    if bbox is None:
        raise ValueError("cached paragraph missing bbox")
    char_bboxes = [_bbox_from_dict(box) for box in raw.get("char_bboxes", [])]
    return ParsedParagraph(
        text=str(raw.get("text") or ""),
        bbox=bbox,
        char_bboxes=[box for box in char_bboxes if box is not None] or None,
        style=raw.get("style"),
    )


def _document_to_cache(doc: ParsedDocument, source_sha256: str) -> dict[str, Any]:
    return {
        "cache_version": _CACHE_VERSION,
        "source_sha256": source_sha256,
        "pages": doc.pages,
        "paragraphs": [_paragraph_to_dict(paragraph) for paragraph in doc.paragraphs],
        "raw_json": doc.raw_json,
        "markdown_text": doc.markdown_text,
        "is_image_pdf": doc.is_image_pdf,
    }


def _document_from_cache(raw: dict[str, Any], expected_sha256: str) -> ParsedDocument:
    if raw.get("cache_version") != _CACHE_VERSION:
        raise ValueError("cache version mismatch")
    if raw.get("source_sha256") != expected_sha256:
        raise ValueError("cache source hash mismatch")

    return ParsedDocument(
        pages=int(raw.get("pages") or 1),
        paragraphs=[_paragraph_from_dict(item) for item in raw.get("paragraphs", [])],
        tables=[],
        raw_json=raw.get("raw_json") or {"engine": "mineru_cache"},
        markdown_text=raw.get("markdown_text"),
        is_image_pdf=bool(raw.get("is_image_pdf", True)),
    )


def parse_image_pdf_with_cache(file_path: Path, cache_dir: Path | None) -> tuple[ParsedDocument, str]:
    source_sha256 = _file_sha256(file_path)
    if cache_dir is None:
        return parse_image_pdf_via_mineru_ocr(str(file_path)), "disabled"

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"mineru_ocr_v{_CACHE_VERSION}_{source_sha256}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return _document_from_cache(cached, source_sha256), "hit"
        except Exception:
            # Treat corrupt or stale cache as a miss; the fresh parse rewrites it.
            pass

    doc = parse_image_pdf_via_mineru_ocr(str(file_path))
    cache_path.write_text(
        json.dumps(_document_to_cache(doc, source_sha256), ensure_ascii=False),
        encoding="utf-8",
    )
    return doc, "miss"


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


def compare_case(
    case: str,
    old_path: Path,
    new_path: Path,
    strategies: list[str],
    *,
    cache_dir: Path | None = None,
    include_hybrid: bool = True,
) -> dict[str, Any]:
    old_ocr, old_cache = parse_image_pdf_with_cache(old_path, cache_dir)
    new_ocr, new_cache = parse_image_pdf_with_cache(new_path, cache_dir)

    result: dict[str, Any] = {
        "case": case,
        "old": str(old_path),
        "new": str(new_path),
        "cache": {"old": old_cache, "new": new_cache},
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
            "_raw_items": items,
        }

    if include_hybrid and {"alignment", "heuristic"} <= set(result["strategies"]):
        hybrid = build_hybrid_recall_candidates(
            result["strategies"]["alignment"]["_raw_items"],
            result["strategies"]["heuristic"]["_raw_items"],
        )
        counts = Counter(candidate.item.diff_type.value for candidate in hybrid)
        result["strategies"]["hybrid"] = {
            "total": len(hybrid),
            "counts": dict(sorted(counts.items())),
            "items": [
                _item_to_dict(
                    candidate.item,
                    **hybrid_candidate_to_dict(candidate),
                )
                for candidate in hybrid
            ],
        }

    for summary in result["strategies"].values():
        summary.pop("_raw_items", None)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    default_cache_dir = Path(os.environ["OCR_CACHE_DIR"]) if os.getenv("OCR_CACHE_DIR") else None
    parser.add_argument("--dm-root", default=os.getenv("DM_ROOT", "/dm"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--strategies", nargs="+", default=["alignment", "heuristic"])
    parser.add_argument("--cache-dir", type=Path, default=default_cache_dir)
    parser.add_argument("--no-hybrid", action="store_true")
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
            case_result = compare_case(
                case,
                old_path,
                new_path,
                strategies,
                cache_dir=args.cache_dir,
                include_hybrid=not args.no_hybrid,
            )
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
        for strategy in [*strategies, "hybrid"]:
            if strategy not in case_result["strategies"]:
                continue
            summary = case_result["strategies"][strategy]
            print(f"{strategy}: total={summary['total']} counts={summary['counts']}")

    payload = {"dm_root": str(root), "cache_dir": str(args.cache_dir) if args.cache_dir else None, "cases": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
