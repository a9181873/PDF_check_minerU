"""
Snapshot service: renders PDF pages with diff overlays and saves audit artifacts.

After each comparison, generates:
  runtime/snapshots/{task_id}/
    metadata.json          - comparison params, diff counts, timestamp
    old_page_{n}.png       - old PDF pages with magenta diff boxes drawn
    new_page_{n}.png       - new PDF pages with magenta diff boxes drawn
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF

from models.diff_models import DiffReport, DiffType

_logger = logging.getLogger(__name__)

# Render resolution (DPI). 150 gives ~A4 at 1240×1754 px — readable, reasonable size.
_DEFAULT_DPI = 150
_SCALE = _DEFAULT_DPI / 72.0

# Magenta (R, G, B) in 0..1 range used for diff rectangle annotations
_DIFF_STROKE = (1.0, 0.0, 1.0)
_DIFF_FILL = (1.0, 0.0, 1.0)
_DIFF_OPACITY = 0.35


def generate_comparison_snapshots(
    task_id: str,
    old_pdf_path: str,
    new_pdf_path: str,
    report: DiffReport,
    snapshot_base_dir: Path,
    diff_pages_only: bool = True,
) -> Path:
    """Render both PDFs with diff overlays and save PNGs + metadata JSON.

    Returns the path to the created snapshot directory.
    """
    snap_dir = snapshot_base_dir / task_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    _render_pdf(
        old_pdf_path,
        report,
        bbox_side="old",
        snap_dir=snap_dir,
        prefix="old",
        diff_pages_only=diff_pages_only,
    )
    _render_pdf(
        new_pdf_path,
        report,
        bbox_side="new",
        snap_dir=snap_dir,
        prefix="new",
        diff_pages_only=diff_pages_only,
    )

    metadata = {
        "task_id": task_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "old_filename": report.old_filename,
        "new_filename": report.new_filename,
        "total_diffs": report.total_diffs,
        "render_dpi": _DEFAULT_DPI,
        "diff_pages_only": diff_pages_only,
        "highlight_color": "#FF00FF",
    }
    (snap_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return snap_dir


def _render_pdf(
    pdf_path: str,
    report: DiffReport,
    bbox_side: str,
    snap_dir: Path,
    prefix: str,
    diff_pages_only: bool,
) -> None:
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        _logger.warning("Snapshot: failed to open %s: %s", pdf_path, exc)
        return

    mat = fitz.Matrix(_SCALE, _SCALE)
    page_bboxes: dict[int, list] = {}
    for item in report.items:
        bbox = item.old_bbox if bbox_side == "old" else item.new_bbox
        if bbox:
            page_bboxes.setdefault(bbox.page, []).append(bbox)

    if diff_pages_only:
        page_numbers = sorted(page for page in page_bboxes if 1 <= page <= len(doc))
    else:
        page_numbers = list(range(1, len(doc) + 1))

    for page_no in page_numbers:
        page_idx = page_no - 1
        page = doc[page_idx]
        page_height = page.rect.height

        for bbox in page_bboxes.get(page_no, []):
            # Our BBox uses bottom-left origin; fitz uses top-left origin.
            fitz_rect = fitz.Rect(
                bbox.x0,
                page_height - bbox.y1,
                bbox.x1,
                page_height - bbox.y0,
            )
            if fitz_rect.is_empty or fitz_rect.is_infinite:
                continue

            try:
                annot = page.add_rect_annot(fitz_rect)
                annot.set_colors(stroke=_DIFF_STROKE, fill=_DIFF_FILL)
                annot.set_opacity(_DIFF_OPACITY)
                annot.update()
            except Exception as exc:
                _logger.debug(
                    "Snapshot: annot failed page=%d bbox=%s: %s", page_no, fitz_rect, exc
                )

        pix = page.get_pixmap(matrix=mat)
        pix.save(str(snap_dir / f"{prefix}_page_{page_no}.png"))

    doc.close()


# Crop rendering for image-diff regions (no text layer available)
_CROP_DPI = 200
_CROP_SCALE = _CROP_DPI / 72.0
_CROP_PADDING_PT = 6.0  # small margin around the region for readability


def generate_diff_crops(
    task_id: str,
    old_pdf_path: str,
    new_pdf_path: str,
    report: DiffReport,
    crops_base_dir: Path,
) -> Path:
    """Render cropped PNGs of IMAGE_DIFF regions from both PDFs.

    Writes `{crops_base_dir}/{task_id}/{diff_id}_{old|new}.png` for each
    IMAGE_DIFF item in the report. Text-based diffs already carry `old_value`
    and `new_value`, so they do not need crops.
    """
    out_dir = crops_base_dir / task_id
    out_dir.mkdir(parents=True, exist_ok=True)

    image_items = [item for item in report.items if item.diff_type == DiffType.IMAGE_DIFF]
    if not image_items:
        return out_dir

    _crop_side(old_pdf_path, image_items, side="old", out_dir=out_dir)
    _crop_side(new_pdf_path, image_items, side="new", out_dir=out_dir)
    return out_dir


def _crop_side(pdf_path: str, items, side: str, out_dir: Path) -> None:
    try:
        doc = fitz.open(pdf_path)
    except Exception as exc:
        _logger.warning("Crop: failed to open %s: %s", pdf_path, exc)
        return

    mat = fitz.Matrix(_CROP_SCALE, _CROP_SCALE)
    try:
        for item in items:
            bbox = item.old_bbox if side == "old" else item.new_bbox
            if not bbox:
                continue
            page_idx = bbox.page - 1
            if page_idx < 0 or page_idx >= len(doc):
                continue

            page = doc[page_idx]
            page_height = page.rect.height
            page_width = page.rect.width

            # Bottom-left origin → top-left origin; pad and clamp to page bounds.
            x0 = max(0.0, bbox.x0 - _CROP_PADDING_PT)
            x1 = min(page_width, bbox.x1 + _CROP_PADDING_PT)
            y0 = max(0.0, page_height - bbox.y1 - _CROP_PADDING_PT)
            y1 = min(page_height, page_height - bbox.y0 + _CROP_PADDING_PT)

            clip = fitz.Rect(x0, y0, x1, y1)
            if clip.is_empty or clip.is_infinite:
                continue

            try:
                pix = page.get_pixmap(matrix=mat, clip=clip)
                pix.save(str(out_dir / f"{item.id}_{side}.png"))
            except Exception as exc:
                _logger.debug(
                    "Crop: render failed id=%s side=%s: %s", item.id, side, exc
                )
    finally:
        doc.close()
