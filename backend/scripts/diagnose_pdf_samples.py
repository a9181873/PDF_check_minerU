from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.diff_service import (
    _extract_priority_ocr_text,
    _ocr_page_region,
    generate_diff_report,
)
from services.parser_service import _parse_via_fitz


PAIR_SPECS = [
    ("baoxinanxin", ("1120209",), ("20240701",)),
    ("fengshouai", ("20260213",), ("20260506",)),
    ("callcard_back", ("Call",), ("Call", "_B")),
]


def _find_one(paths: list[Path], needles: tuple[str, ...], exclude: tuple[str, ...] = ()) -> Path | None:
    hits = [
        path
        for path in paths
        if all(needle in path.name for needle in needles)
        and not any(skip in path.name for skip in exclude)
    ]
    return hits[0] if len(hits) == 1 else None


def _auto_pairs(paths: list[Path]) -> list[tuple[str, Path, Path]]:
    pairs: list[tuple[str, Path, Path]] = []
    by_parent: dict[Path, list[Path]] = {}
    for path in paths:
        by_parent.setdefault(path.parent, []).append(path)

    for parent, group in sorted(by_parent.items(), key=lambda item: str(item[0])):
        group = sorted(group, key=lambda path: path.name)
        if len(group) == 2:
            pairs.append((f"auto:{parent.name}", group[0], group[1]))
    return pairs


def _scan_pdf(path: Path) -> dict:
    doc_info = _parse_via_fitz(path)
    pages: list[dict] = []
    with fitz.open(path) as doc:
        for page_no, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            words = page.get_text("words") or []
            blocks = page.get_text("rawdict").get("blocks", [])
            image_blocks = sum(1 for block in blocks if block.get("type") == 1)
            width = float(page.rect.width)
            height = float(page.rect.height)
            top_rect = fitz.Rect(0, 0, width, height * 0.14)
            bottom_rect = fitz.Rect(0, height * 0.84, width, height)
            top_ocr = _ocr_page_region(page, top_rect, zoom=3.0, lang="chi_tra+eng", psm="6")
            bottom_ocr = _ocr_page_region(page, bottom_rect, zoom=4.0, lang="chi_tra+eng", psm="6")
            pages.append(
                {
                    "page": page_no,
                    "chars": len(text.strip()),
                    "words": len(words),
                    "images": len(page.get_images(full=True)),
                    "image_blocks": image_blocks,
                    "size": f"{width:.1f}x{height:.1f}",
                    "native_sample": " ".join(text.split())[:180],
                    "top_priority": _extract_priority_ocr_text(top_ocr),
                    "bottom_priority": _extract_priority_ocr_text(bottom_ocr),
                    "top_ocr": " ".join(top_ocr.split())[:220],
                    "bottom_ocr": " ".join(bottom_ocr.split())[:260],
                }
            )
    return {
        "is_image_pdf": doc_info.is_image_pdf,
        "paragraphs": len(doc_info.paragraphs),
        "pages": pages,
    }


def _print_pdf_scan(label: str, side: str, path: Path) -> None:
    info = _scan_pdf(path)
    print(f"{side}: {path}")
    print(f"  image_pdf={info['is_image_pdf']} paragraphs={info['paragraphs']}")
    for page in info["pages"]:
        print(
            "  p{page}: chars={chars} words={words} images={images} "
            "image_blocks={image_blocks} size={size}".format(**page)
        )
        if page["native_sample"]:
            print(f"    native: {page['native_sample']}")
        if page["top_priority"]:
            print(f"    top priority: {page['top_priority']}")
        if page["bottom_priority"]:
            print(f"    bottom priority: {page['bottom_priority']}")
        print(f"    ocr top: {page['top_ocr']}")
        print(f"    ocr bottom: {page['bottom_ocr']}")


def _print_report(label: str, old_path: Path, new_path: Path) -> None:
    old_doc = _parse_via_fitz(old_path)
    new_doc = _parse_via_fitz(new_path)
    report = generate_diff_report(
        label,
        old_path.name,
        new_path.name,
        old_doc,
        new_doc,
        str(old_path),
        str(new_path),
    )
    counts = Counter(item.diff_type.value for item in report.items)
    with_text = sum(1 for item in report.items if item.old_value or item.new_value)
    with_crop = sum(1 for item in report.items if item.old_image_base64 or item.new_image_base64)
    both = sum(
        1
        for item in report.items
        if (item.old_value or item.new_value)
        and (item.old_image_base64 or item.new_image_base64)
    )
    print(f"REPORT: {report.summary}")
    print(f"  total={report.total_diffs} types={dict(counts)} with_text={with_text} with_crop={with_crop} text_and_crop={both}")
    for item in report.items[:25]:
        bbox = item.new_bbox or item.old_bbox
        bbox_text = (
            f"p{bbox.page} ({bbox.x0:.1f},{bbox.y0:.1f},{bbox.x1:.1f},{bbox.y1:.1f})"
            if bbox
            else "no-bbox"
        )
        old_value = (item.old_value or "").replace("\n", " ")[:100]
        new_value = (item.new_value or "").replace("\n", " ")[:100]
        print(
            f"  {item.id} {item.diff_type.value} {bbox_text} "
            f"text={bool(old_value or new_value)} crop={bool(item.old_image_base64 or item.new_image_base64)} "
            f"{old_value!r} => {new_value!r} | {item.context[:80]}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--skip-report", action="store_true")
    args = parser.parse_args()

    paths = sorted(
        {
            path
            for root in args.roots
            if root.exists()
            for path in root.rglob("*.pdf")
        },
        key=lambda path: str(path),
    )
    print(f"PDF_COUNT: {len(paths)}")
    for path in paths:
        print(f"  {path}")

    pairs: list[tuple[str, Path, Path]] = []
    for label, old_needles, new_needles in PAIR_SPECS:
        old_path = _find_one(paths, old_needles, exclude=("_B",) if label == "callcard_back" else ())
        new_path = _find_one(paths, new_needles)
        if old_path and new_path:
            pairs.append((label, old_path, new_path))

    known = {path for _, old_path, new_path in pairs for path in (old_path, new_path)}
    pairs.extend(
        (label, old_path, new_path)
        for label, old_path, new_path in _auto_pairs([path for path in paths if path not in known])
    )

    print(f"PAIR_COUNT: {len(pairs)}")
    for label, old_path, new_path in pairs:
        print(f"\n=== {label} ===")
        _print_pdf_scan(label, "OLD", old_path)
        _print_pdf_scan(label, "NEW", new_path)
        if not args.skip_report:
            _print_report(label, old_path, new_path)


if __name__ == "__main__":
    main()
