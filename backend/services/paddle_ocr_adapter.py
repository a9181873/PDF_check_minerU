"""Optional PaddleOCR adapter for local / intranet OCR experiments.

This module deliberately has no import-time dependency on PaddleOCR. Enterprise
deployments can keep the feature disabled until the PaddleOCR package and model
files are baked into the Docker image or installed in an offline environment.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from models.diff_models import BBox
from services.parser_service import ParsedDocument, ParsedParagraph
from services.pymupdf_guard import pymupdf_serialized


def _bbox_from_points(page: int, page_height: float, points: list[list[float]]) -> BBox:
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    x0, x1 = min(xs), max(xs)
    y0_top, y1_top = min(ys), max(ys)
    return BBox(page=page, x0=x0, y0=page_height - y1_top, x1=x1, y1=page_height - y0_top)


def _extract_lines(raw_result: Any) -> list[tuple[list[list[float]], str, float]]:
    """Normalize PaddleOCR 2.x style output into (bbox_points, text, score)."""
    lines: list[tuple[list[list[float]], str, float]] = []
    pages = raw_result if isinstance(raw_result, list) else [raw_result]
    for page in pages:
        if not page:
            continue
        for entry in page:
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            points = entry[0]
            text_score = entry[1]
            if not isinstance(text_score, (list, tuple)) or len(text_score) < 2:
                continue
            text = str(text_score[0] or "").strip()
            if not text:
                continue
            try:
                score = float(text_score[1])
            except (TypeError, ValueError):
                score = 0.0
            lines.append((points, text, score))
    return lines


@pymupdf_serialized
def parse_image_pdf_via_paddleocr(
    file_path: str,
    *,
    dpi: int = 200,
    lang: str = "ch",
    max_pages: int | None = None,
    min_confidence: float = 0.35,
    regions: list[BBox] | None = None,
) -> ParsedDocument:
    """Parse a PDF through local PaddleOCR and return positioned paragraphs.

    Raises RuntimeError when PaddleOCR/PyMuPDF/Pillow is unavailable or when the
    local PaddleOCR API shape is unsupported. Callers should treat this as an
    optional second engine and degrade gracefully.
    """
    try:
        import fitz
        from PIL import Image
        from paddleocr import PaddleOCR
    except ImportError as exc:
        raise RuntimeError(f"PaddleOCR dependencies unavailable: {exc}") from exc

    pdf_path = Path(file_path)
    doc = fitz.open(pdf_path)
    paragraphs: list[ParsedParagraph] = []
    page_count = len(doc)
    page_limit = min(page_count, max_pages) if max_pages else page_count
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    scale_to_pt = 72.0 / dpi

    try:
        ocr = PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)
    except TypeError:
        # PaddleOCR 3.x changed some constructor arguments; keep this adapter
        # tolerant so experiments can run across minor package versions.
        ocr = PaddleOCR(lang=lang)

    try:
        with tempfile.TemporaryDirectory(prefix="paddleocr_pdf_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            for page_index in range(page_limit):
                page = doc[page_index]
                page_regions = [region for region in (regions or []) if region.page == page_index + 1]
                if regions is not None and not page_regions:
                    continue
                clips = page_regions or [None]
                for region_index, region in enumerate(clips, start=1):
                    clip = None
                    offset_x = offset_y_top = 0.0
                    if region is not None:
                        clip = fitz.Rect(
                            region.x0,
                            page.rect.height - region.y1,
                            region.x1,
                            page.rect.height - region.y0,
                        )
                        offset_x, offset_y_top = float(clip.x0), float(clip.y0)
                    pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
                    image_path = tmp_path / f"page_{page_index + 1}_region_{region_index}.png"
                    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    image.save(image_path)

                    if not hasattr(ocr, "ocr"):
                        raise RuntimeError("Installed PaddleOCR object has no supported ocr() method")
                    raw = ocr.ocr(str(image_path), cls=True)
                    for points, text, score in _extract_lines(raw):
                        if score < min_confidence:
                            continue
                        scaled_points = [
                            [
                                float(x) * scale_to_pt + offset_x,
                                float(y) * scale_to_pt + offset_y_top,
                            ]
                            for x, y in points
                        ]
                        paragraphs.append(
                            ParsedParagraph(
                                text=text,
                                bbox=_bbox_from_points(page_index + 1, page.rect.height, scaled_points),
                                style=f"paddleocr:{score:.3f}",
                            )
                        )
    finally:
        doc.close()

    return ParsedDocument(
        pages=page_count,
        paragraphs=paragraphs,
        tables=[],
        raw_json={
            "source": "paddleocr",
            "lang": lang,
            "dpi": dpi,
            "max_pages": max_pages,
            "region_count": len(regions) if regions is not None else None,
        },
        is_image_pdf=True,
    )
