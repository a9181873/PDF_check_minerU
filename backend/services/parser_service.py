import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
import unicodedata
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pandas as pd

from models.diff_models import BBox

DEFAULT_PAGE_WIDTH_PT = 595.0
DEFAULT_PAGE_HEIGHT_PT = 842.0


@dataclass
class ParsedParagraph:
    text: str
    bbox: BBox
    char_bboxes: list[BBox] | None = None
    style: str | None = None


@dataclass
class ParsedTable:
    dataframe: pd.DataFrame
    bbox: BBox
    caption: str | None = None
    header_rows: int = 1
    cell_bboxes: dict[tuple[int, int], BBox] = None

    def __post_init__(self):
        if self.cell_bboxes is None:
            self.cell_bboxes = {}


@dataclass
class ParsedDocument:
    pages: int
    paragraphs: list[ParsedParagraph]
    tables: list[ParsedTable]
    raw_json: dict
    markdown_text: str | None = None
    is_image_pdf: bool = False


_PARSE_CACHE_LOCK = threading.RLock()
_PARSE_CACHE: OrderedDict[str, ParsedDocument] = OrderedDict()
_PARSE_INFLIGHT: dict[str, threading.Event] = {}
_HEAVY_SEMAPHORE_LOCK = threading.Lock()
_HEAVY_SEMAPHORES: dict[int, threading.BoundedSemaphore] = {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser_cache_key(pdf_path: Path) -> str:
    from config import settings

    fingerprint = "|".join(
        [
            "parser-v2",
            settings.table_parser_strategy,
            str(bool(settings.enable_docling_parallel)),
            str(bool(settings.enable_lightweight_table_probe)),
            str(float(settings.mineru_preferred_wait_seconds)),
            str(settings.mineru_api_url or os.getenv("MINERU_API_URL", "")),
            os.getenv("OCR_LANGS", "chi_tra+chi_sim+eng"),
        ]
    )
    return f"{_sha256_file(pdf_path)}:{hashlib.sha256(fingerprint.encode()).hexdigest()[:16]}"


def _with_cache_status(document: ParsedDocument, *, hit: bool) -> ParsedDocument:
    raw_json = dict(document.raw_json or {})
    routing = dict(raw_json.get("routing") or {})
    routing["cache_hit"] = hit
    raw_json["routing"] = routing
    return ParsedDocument(
        pages=document.pages,
        paragraphs=document.paragraphs,
        tables=document.tables,
        raw_json=raw_json,
        markdown_text=document.markdown_text,
        is_image_pdf=document.is_image_pdf,
    )


def clear_parse_cache() -> None:
    """Clear the bounded in-process parse cache (tests / controlled maintenance)."""
    with _PARSE_CACHE_LOCK:
        _PARSE_CACHE.clear()
        for event in _PARSE_INFLIGHT.values():
            event.set()
        _PARSE_INFLIGHT.clear()


def _heavy_parser_semaphore() -> threading.BoundedSemaphore:
    from config import settings

    limit = max(1, int(settings.heavy_parser_max_concurrency))
    with _HEAVY_SEMAPHORE_LOCK:
        return _HEAVY_SEMAPHORES.setdefault(limit, threading.BoundedSemaphore(limit))


@contextmanager
def _heavy_parser_slot(trace: dict):
    semaphore = _heavy_parser_semaphore()
    queued_at = time.perf_counter()
    semaphore.acquire()
    trace["queue_wait_seconds"] = round(time.perf_counter() - queued_at, 4)
    try:
        yield
    finally:
        semaphore.release()


def _to_bottom_left_bbox(page_number: int, page_height: float, block_bbox: list[float]) -> BBox:
    x0, y0_top, x1, y1_top = block_bbox
    y0 = page_height - y1_top
    y1 = page_height - y0_top
    return BBox(page=page_number, x0=x0, y0=y0, x1=x1, y1=y1)


def _synthetic_paragraph_bbox(page: int, line_index: int, total_lines: int) -> BBox:
    line_height = DEFAULT_PAGE_HEIGHT_PT / max(total_lines, 1)
    y_top = line_index * line_height
    y_bottom = min((line_index + 1) * line_height, DEFAULT_PAGE_HEIGHT_PT)
    return BBox(
        page=page,
        x0=0.0,
        y0=DEFAULT_PAGE_HEIGHT_PT - y_bottom,
        x1=DEFAULT_PAGE_WIDTH_PT,
        y1=DEFAULT_PAGE_HEIGHT_PT - y_top,
    )


def _span_text(span: dict) -> str:
    text = str(span.get("text") or "")
    if text:
        return text
    chars = span.get("chars") or []
    return "".join(str(ch.get("c") or "") for ch in chars)


def _bbox_from_docling(
    *,
    page_no: int,
    bbox_obj,
    page_height: float,
) -> BBox:
    x0 = float(getattr(bbox_obj, "l", 0.0))
    y_top = float(getattr(bbox_obj, "t", 0.0))
    x1 = float(getattr(bbox_obj, "r", 0.0))
    y_bottom = float(getattr(bbox_obj, "b", 0.0))
    coord_origin = str(getattr(getattr(bbox_obj, "coord_origin", None), "value", "")).upper()

    if "TOP" in coord_origin:
        y0 = page_height - y_bottom
        y1 = page_height - y_top
    else:
        y0 = y_bottom
        y1 = y_top
    return BBox(page=page_no, x0=x0, y0=y0, x1=x1, y1=y1)


@lru_cache(maxsize=1)
def _get_docling_converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    lang_env = os.getenv("OCR_LANGS", "chi_tra+chi_sim+eng")
    langs = [lang.strip() for lang in lang_env.split(",") if lang.strip()]

    options = PdfPipelineOptions()
    # do_ocr=True but force_full_page_ocr=False: only OCR truly image-based pages.
    # For PDFs with embedded text (like insurance DMs), the text layer is used directly,
    # which avoids OCR-induced false positives from Tesseract misreads.
    options.do_ocr = True
    options.ocr_options = TesseractCliOcrOptions(
        lang=langs or ["chi_tra", "chi_sim", "eng"],
        force_full_page_ocr=False,
    )

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options),
        }
    )


# ── MinerU helpers ────────────────────────────────────────────────────────────

def _get_page_sizes_fitz(pdf_path: Path) -> dict[int, tuple[float, float]]:
    """Return {page_no (1-based): (width_pt, height_pt)} using PyMuPDF."""
    try:
        import fitz
        with fitz.open(pdf_path) as doc:
            return {
                i + 1: (float(page.rect.width), float(page.rect.height))
                for i, page in enumerate(doc)
            }
    except Exception:
        return {}


def _mineru_bbox_to_bbox(raw: list, page_no: int, page_width: float, page_height: float) -> BBox:
    """Convert a MinerU content_list bbox to a bottom-left-origin BBox.

    MinerU ``content_list.json`` bboxes are normalised to a 0–1000 coordinate
    space with a top-left origin — verified empirically against the repo's own
    outputs, where x/y maxima cluster at ~968–983 regardless of page size or
    page count (see docs/historical_issues.md §7). Scale back to PDF points
    using the real page size, then flip Y to a bottom-left origin. When the page
    size is unknown (<= 0) fall back to treating the values as raw points so a
    missing fitz page cannot break the conversion.
    """
    x0n, y0n_top, x1n, y1n_top = float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3])
    if page_width > 0 and page_height > 0:
        sx = page_width / 1000.0
        sy = page_height / 1000.0
        x0, x1 = x0n * sx, x1n * sx
        y0_top, y1_top = y0n_top * sy, y1n_top * sy
    else:
        x0, x1, y0_top, y1_top = x0n, x1n, y0n_top, y1n_top
    return BBox(page=page_no, x0=x0, y0=page_height - y1_top, x1=x1, y1=page_height - y0_top)


def _normalize_mineru_text(text: str) -> str:
    """NFKC normalise to collapse 繁簡混用 edge cases from OCR pipeline."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _html_table_to_dataframe(html: str) -> pd.DataFrame:
    """Parse MinerU HTML table → DataFrame, handling rowspan/colspan via lxml/html5lib."""
    if not html.strip():
        return pd.DataFrame()
    try:
        dfs = pd.read_html(html, flavor="lxml")
        if dfs:
            return dfs[0].fillna("").astype(str)
    except Exception:
        pass
    try:
        dfs = pd.read_html(html)
        if dfs:
            return dfs[0].fillna("").astype(str)
    except Exception:
        pass
    return pd.DataFrame()


def _parse_via_mineru(
    pdf_path: Path,
    page_sizes: dict[int, tuple[float, float]],
    parse_method: str = "auto",
) -> ParsedDocument:
    """Call MinerU REST API to extract tables and text.

    Uses pipeline backend with chinese_cht language to minimise
    Traditional/Simplified Chinese mixing in OCR output. ``parse_method`` is
    "auto" for text-layer PDFs and "ocr" to force OCR on image-only PDFs (the
    recall layer). Falls back gracefully if the service is unavailable.
    """
    import requests as _requests

    from config import settings

    url = (settings.mineru_api_url or os.getenv("MINERU_API_URL", "")).rstrip("/")
    if not url:
        raise RuntimeError("MINERU_API_URL not configured")

    with open(pdf_path, "rb") as f:
        resp = _requests.post(
            f"{url}/file_parse",
            files={"files": (pdf_path.name, f, "application/pdf")},
            data={
                "backend": "pipeline",
                "lang_list": "chinese_cht",
                "parse_method": parse_method,
                "return_md": "true",
                "return_content_list": "true",
            },
            timeout=max(1.0, float(settings.mineru_timeout_seconds)),
        )
    resp.raise_for_status()

    data = resp.json()
    results = data.get("results", {})
    # Key is the file stem (filename without .pdf)
    stem = pdf_path.stem
    item = results.get(stem) or (next(iter(results.values()), {}) if results else {})

    md = item.get("md_content", "") or ""
    cl_raw = item.get("content_list", [])
    cl: list = json.loads(cl_raw) if isinstance(cl_raw, str) else (cl_raw or [])

    paragraphs: list[ParsedParagraph] = []
    tables: list[ParsedTable] = []

    for block in cl:
        if not isinstance(block, dict):
            continue

        btype = block.get("type", "")
        raw_bbox = block.get("bbox") or []
        # MinerU uses 0-based page_idx
        page_no = int(block.get("page_idx", 0)) + 1
        page_w, page_h = page_sizes.get(page_no, (DEFAULT_PAGE_WIDTH_PT, DEFAULT_PAGE_HEIGHT_PT))

        bbox = (
            _mineru_bbox_to_bbox(raw_bbox, page_no, page_w, page_h)
            if len(raw_bbox) == 4 else None
        )

        if btype == "text":
            text = _normalize_mineru_text(block.get("text", "") or "")
            if text and bbox:
                paragraphs.append(ParsedParagraph(text=text, bbox=bbox))

        elif btype == "table":
            html = block.get("table_body", "") or ""
            caption_raw = block.get("table_caption") or []
            caption = (
                caption_raw[0] if isinstance(caption_raw, list) and caption_raw
                and isinstance(caption_raw[0], str)
                else (caption_raw if isinstance(caption_raw, str) else None)
            )
            df = _html_table_to_dataframe(html)
            if bbox:
                tables.append(ParsedTable(
                    dataframe=df,
                    bbox=bbox,
                    caption=caption,
                    header_rows=1,
                    cell_bboxes={},  # cell-level bbox not available from MinerU HTML
                ))

    total_pages = max(page_sizes.keys()) if page_sizes else max(
        (int(b.get("page_idx", 0)) + 1 for b in cl if isinstance(b, dict)), default=1
    )

    return ParsedDocument(
        pages=total_pages,
        paragraphs=paragraphs,
        tables=tables,
        raw_json={
            "engine": "mineru",
            "raw_preview": md[:3000],
            "paragraph_count": len(paragraphs),
            "table_count": len(tables),
        },
        markdown_text=md or None,
    )


# ── Docling ───────────────────────────────────────────────────────────────────

def _parse_via_docling(pdf_path: Path) -> ParsedDocument:
    converter = _get_docling_converter()
    result = converter.convert(str(pdf_path))

    doc_obj = result.document
    page_heights = {}
    for page_no, page_item in getattr(doc_obj, "pages", {}).items():
        size = getattr(page_item, "size", None)
        if size and hasattr(size, "height"):
            page_heights[int(page_no)] = float(size.height)

    paragraphs: list[ParsedParagraph] = []
    for entry in doc_obj.iterate_items():
        item = entry[0]
        prov = getattr(item, "prov", None)
        if not prov:
            continue

        text = ""
        for attr in ("text", "orig", "md_content", "content"):
            value = getattr(item, attr, None)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                break
        if not text:
            continue

        first_prov = prov[0]
        page_no = int(getattr(first_prov, "page_no", 1))
        page_height = page_heights.get(page_no, DEFAULT_PAGE_HEIGHT_PT)

        if type(item).__name__ == "TableItem":
            # Tables are handled separately in the tables list
            continue

        bbox_obj = getattr(first_prov, "bbox", None)
        if not bbox_obj:
            continue


        bbox = _bbox_from_docling(page_no=page_no, bbox_obj=bbox_obj, page_height=page_height)
        paragraphs.append(ParsedParagraph(text=text, bbox=bbox))

    tables: list[ParsedTable] = []
    for table_item in getattr(doc_obj, "tables", []):
        prov = getattr(table_item, "prov", None)
        if not prov:
            continue
        first_prov = prov[0]
        page_no = int(getattr(first_prov, "page_no", 1))
        bbox_obj = getattr(first_prov, "bbox", None)
        if not bbox_obj:
            continue
        page_height = page_heights.get(page_no, DEFAULT_PAGE_HEIGHT_PT)
        table_bbox = _bbox_from_docling(page_no=page_no, bbox_obj=bbox_obj, page_height=page_height)

        dataframe = pd.DataFrame()
        try:
            dataframe = table_item.export_to_dataframe(doc=doc_obj)
        except Exception:
            try:
                dataframe = table_item.export_to_dataframe()
            except Exception:
                dataframe = pd.DataFrame()

        caption = getattr(table_item, "caption_text", None)
        
        # Populate cell bboxes
        cell_bboxes = {}
        data = getattr(table_item, "data", None)
        cells = getattr(data, "table_cells", []) if data else []
        for cell in cells:
            c_text = str(getattr(cell, "text", "")).strip()
            # Docling uses 0-based row/col for some, but let's check attributes
            row_idx = getattr(cell, "row_index", None)
            col_idx = getattr(cell, "col_index", None)
            if row_idx is not None and col_idx is not None:
                c_prov = getattr(cell, "prov", None)
                if c_prov:
                    c_bbox_obj = getattr(c_prov[0], "bbox", None)
                    if c_bbox_obj:
                        c_page_no = int(getattr(c_prov[0], "page_no", page_no))
                        c_page_height = page_heights.get(c_page_no, DEFAULT_PAGE_HEIGHT_PT)
                        cell_bboxes[(row_idx, col_idx)] = _bbox_from_docling(
                            page_no=c_page_no, bbox_obj=c_bbox_obj, page_height=c_page_height
                        )

        tables.append(
            ParsedTable(
                dataframe=dataframe,
                bbox=table_bbox,
                caption=caption if isinstance(caption, str) and caption.strip() else None,
                header_rows=1,
                cell_bboxes=cell_bboxes
            )
        )

    markdown = ""
    if hasattr(doc_obj, "export_to_markdown"):
        markdown = doc_obj.export_to_markdown() or ""

    if not paragraphs and markdown:
        # Safety net: if structured items are missing, keep minimal text lines.
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        for line_index, line in enumerate(lines):
            paragraphs.append(
                ParsedParagraph(
                    text=line,
                    bbox=_synthetic_paragraph_bbox(1, line_index, len(lines)),
                )
            )

    return ParsedDocument(
        pages=max(len(getattr(doc_obj, "pages", {})), 1),
        paragraphs=paragraphs,
        tables=tables,
        raw_json={
            "engine": "docling",
            "raw_preview": markdown[:3000],
            "paragraph_count": len(paragraphs),
            "table_count": len(tables),
        },
        markdown_text=markdown or None,
    )


def _opendataloader_bbox(node: dict, fallback_page: int = 1) -> BBox | None:
    raw = node.get("bounding box") or node.get("bounding_box") or []
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(value) for value in raw)
        page = max(1, int(node.get("page number") or node.get("page_number") or fallback_page))
        return BBox(
            page=page,
            x0=min(x0, x1),
            y0=min(y0, y1),
            x1=max(x0, x1),
            y1=max(y0, y1),
        )
    except (TypeError, ValueError):
        return None


def _opendataloader_text(node: dict) -> str:
    parts: list[str] = []
    content = node.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    for key in ("kids", "list items"):
        children = node.get(key) or []
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    child_text = _opendataloader_text(child)
                    if child_text:
                        parts.append(child_text)
    return " ".join(dict.fromkeys(parts))


def _union_bboxes(boxes: list[BBox]) -> BBox | None:
    if not boxes:
        return None
    page = boxes[0].page
    same_page = [box for box in boxes if box.page == page]
    return BBox(
        page=page,
        x0=min(box.x0 for box in same_page),
        y0=min(box.y0 for box in same_page),
        x1=max(box.x1 for box in same_page),
        y1=max(box.y1 for box in same_page),
    )


def _opendataloader_cell_bbox(cell: dict, fallback_page: int) -> BBox | None:
    direct = _opendataloader_bbox(cell, fallback_page)
    if direct:
        return direct
    boxes: list[BBox] = []

    def collect(node: dict, page: int) -> None:
        bbox = _opendataloader_bbox(node, page)
        if bbox:
            boxes.append(bbox)
            page = bbox.page
        for child in node.get("kids") or []:
            if isinstance(child, dict):
                collect(child, page)

    collect(cell, fallback_page)
    return _union_bboxes(boxes)


def _parsedocument_from_opendataloader_json(payload: dict) -> ParsedDocument:
    """Map OpenDataLoader's hierarchical JSON into the existing parser contract."""
    paragraphs: list[ParsedParagraph] = []
    tables: list[ParsedTable] = []
    text_types = {"paragraph", "heading", "caption", "list item"}

    def parse_table(node: dict, page: int) -> None:
        table_bbox = _opendataloader_bbox(node, page)
        rows = node.get("rows") or []
        row_count = max(int(node.get("number of rows") or 0), len(rows))
        col_count = int(node.get("number of columns") or 0)
        for row in rows:
            for cell in row.get("cells") or []:
                try:
                    col_count = max(col_count, int(cell.get("column number") or 0))
                    row_count = max(row_count, int(cell.get("row number") or 0))
                except (TypeError, ValueError):
                    continue
        if row_count <= 0 or col_count <= 0:
            return

        grid = [["" for _ in range(col_count)] for _ in range(row_count)]
        cell_bboxes: dict[tuple[int, int], BBox] = {}
        for row in rows:
            for cell in row.get("cells") or []:
                try:
                    row_idx = max(0, int(cell.get("row number") or 1) - 1)
                    col_idx = max(0, int(cell.get("column number") or 1) - 1)
                except (TypeError, ValueError):
                    continue
                if row_idx >= row_count or col_idx >= col_count:
                    continue
                grid[row_idx][col_idx] = _opendataloader_text(cell)
                cell_bbox = _opendataloader_cell_bbox(cell, page)
                if cell_bbox:
                    cell_bboxes[(row_idx, col_idx)] = cell_bbox

        if table_bbox is None:
            table_bbox = _union_bboxes(list(cell_bboxes.values()))
        if table_bbox is None:
            return

        header = grid[0]
        dataframe = pd.DataFrame(grid[1:], columns=header) if len(grid) > 1 else pd.DataFrame(columns=header)
        tables.append(
            ParsedTable(
                dataframe=dataframe.fillna("").astype(str),
                bbox=table_bbox,
                header_rows=1,
                cell_bboxes=cell_bboxes,
            )
        )

    def visit(node: dict, inherited_page: int = 1, inside_table: bool = False) -> None:
        node_type = str(node.get("type") or "").strip().lower()
        bbox = _opendataloader_bbox(node, inherited_page)
        page = bbox.page if bbox else max(
            1,
            int(node.get("page number") or node.get("page_number") or inherited_page),
        )
        if node_type == "table":
            parse_table(node, page)
            inside_table = True
        elif not inside_table and node_type in text_types:
            text = str(node.get("content") or "").strip()
            if text and bbox:
                paragraphs.append(ParsedParagraph(text=text, bbox=bbox, style=node_type))

        child_keys = ("kids", "list items")
        if node_type != "table":
            child_keys += ("rows", "cells")
        for key in child_keys:
            children = node.get(key) or []
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, dict):
                        visit(child, page, inside_table)

    for child in payload.get("kids") or []:
        if isinstance(child, dict):
            visit(child)

    markdown = "\n\n".join(paragraph.text for paragraph in paragraphs)
    return ParsedDocument(
        pages=max(1, int(payload.get("number of pages") or 1)),
        paragraphs=paragraphs,
        tables=tables,
        raw_json={
            "engine": "opendataloader",
            "paragraph_count": len(paragraphs),
            "table_count": len(tables),
        },
        markdown_text=markdown or None,
    )


def _parse_via_opendataloader(pdf_path: Path) -> ParsedDocument:
    """Optional OpenDataLoader local adapter; requires its package and Java 11+."""
    try:
        import opendataloader_pdf
    except ModuleNotFoundError as exc:
        raise RuntimeError("OpenDataLoader Python package is not installed") from exc

    with tempfile.TemporaryDirectory(prefix="opendataloader_") as temp_dir:
        opendataloader_pdf.convert(
            input_path=str(pdf_path),
            output_dir=temp_dir,
            format="json",
        )
        candidates = sorted(Path(temp_dir).rglob("*.json"))
        for candidate in candidates:
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and "kids" in payload:
                return _parsedocument_from_opendataloader_json(payload)
    raise RuntimeError("OpenDataLoader did not produce a valid JSON document")


_NUMERIC_WORD_RE = re.compile(r"\d")


def _page_has_numeric_grid(page) -> bool:
    """Cheap signal for borderless rate tables: repeated numeric rows/columns."""
    rows: dict[int, list[tuple[float, str]]] = {}
    for word in page.get_text("words") or []:
        if len(word) < 5:
            continue
        text = str(word[4] or "").strip()
        if not text or not _NUMERIC_WORD_RE.search(text):
            continue
        y_bucket = round(float(word[1]) / 4.0)
        rows.setdefault(y_bucket, []).append((float(word[0]), text))
    numeric_rows = [values for values in rows.values() if len(values) >= 2]
    if len(numeric_rows) < 3:
        return False
    # Repeated X bands distinguish a grid from ordinary prose containing dates.
    bands: dict[int, int] = {}
    for values in numeric_rows:
        for x0, _ in values:
            band = round(x0 / 18.0)
            bands[band] = bands.get(band, 0) + 1
    return sum(1 for count in bands.values() if count >= 3) >= 2


def _probe_page_table_candidates(page) -> int:
    """Detect ruled tables without loading ML models; numeric grids cover borderless rate tables."""
    candidates = 1 if _page_has_numeric_grid(page) else 0

    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []

    def add_line(x0: float, y0: float, x1: float, y1: float) -> None:
        if abs(y1 - y0) <= 1.5 and abs(x1 - x0) >= 20:
            horizontal.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2))
        elif abs(x1 - x0) <= 1.5 and abs(y1 - y0) >= 20:
            vertical.append(((x0 + x1) / 2, min(y0, y1), max(y0, y1)))

    for drawing in page.get_drawings() or []:
        for item in drawing.get("items") or []:
            if item[0] == "l":
                p0, p1 = item[1], item[2]
                add_line(float(p0.x), float(p0.y), float(p1.x), float(p1.y))
            elif item[0] == "re":
                rect = item[1]
                add_line(rect.x0, rect.y0, rect.x1, rect.y0)
                add_line(rect.x0, rect.y1, rect.x1, rect.y1)
                add_line(rect.x0, rect.y0, rect.x0, rect.y1)
                add_line(rect.x1, rect.y0, rect.x1, rect.y1)

    def dedupe(lines: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
        unique: dict[tuple[int, int, int], tuple[float, float, float]] = {}
        for values in lines:
            key = tuple(round(value / 2.0) for value in values)
            unique.setdefault(key, values)
        return list(unique.values())

    horizontal = dedupe(horizontal)
    vertical = dedupe(vertical)

    # Find a connected grid instead of counting unrelated page/card borders.
    # Three vertical boundaries and four spanning horizontal boundaries represent
    # at least a 2-column x 3-row business table; smaller decorative boxes stay fast.
    for x0, x1, y in horizontal:
        crossing = [
            (x, vy0, vy1)
            for x, vy0, vy1 in vertical
            if x0 - 2 <= x <= x1 + 2 and vy0 - 2 <= y <= vy1 + 2
        ]
        if len(crossing) < 3:
            continue
        min_x = min(item[0] for item in crossing)
        max_x = max(item[0] for item in crossing)
        spanning_y = {
            round(hy / 2.0)
            for hx0, hx1, hy in horizontal
            if hx0 <= min_x + 2
            and hx1 >= max_x - 2
            and sum(1 for x, vy0, vy1 in crossing if vy0 - 2 <= hy <= vy1 + 2) >= 3
        }
        if len(spanning_y) >= 4:
            candidates += 1
            break
    return candidates


def _parse_via_fitz(pdf_path: Path) -> ParsedDocument:
    import fitz

    paragraphs: list[ParsedParagraph] = []
    image_pages = 0
    total_pages = 0
    table_candidates = 0
    table_probe_errors = 0

    with fitz.open(pdf_path) as doc:
        total_pages = len(doc)
        for page_index, page in enumerate(doc, start=1):
            page_dict = page.get_text("rawdict")
            page_height = float(page.rect.height)
            page_image_count = len(page.get_images())
            page_char_count = 0

            for block in page_dict.get("blocks", []):
                if block.get("type") != 0:
                    continue

                lines = block.get("lines", [])
                for line in lines:
                    parts: list[str] = []
                    line_char_bboxes: list[BBox] = []

                    for span in line.get("spans", []):
                        # Use character-level info if available in rawdict
                        chars = span.get("chars", [])
                        if chars:
                            for c in chars:
                                c_bbox = _to_bottom_left_bbox(
                                    page_number=page_index,
                                    page_height=page_height,
                                    block_bbox=c.get("bbox", [0, 0, 0, 0]),
                                )
                                line_char_bboxes.append(c_bbox)

                        text = _span_text(span)
                        if text:
                            parts.append(text)

                    joined = "".join(parts) # Don't strip or space-join if we want exact char alignment
                    if not joined.strip():
                        continue

                    page_char_count += len(joined)
                    line_bbox = _to_bottom_left_bbox(
                        page_number=page_index,
                        page_height=page_height,
                        block_bbox=line.get("bbox", [0, 0, 0, 0]),
                    )
                    paragraphs.append(ParsedParagraph(
                        text=joined,
                        bbox=line_bbox,
                        char_bboxes=line_char_bboxes if len(line_char_bboxes) == len(joined) else None
                    ))

            if page_char_count < 10 and page_image_count > 0:
                image_pages += 1
            elif page_char_count >= 10:
                try:
                    table_candidates += _probe_page_table_candidates(page)
                except Exception:
                    # Uncertain means the heavy parser must still run; never turn a
                    # probe failure into a silent table false negative.
                    table_probe_errors += 1

        # Per-page judgement: only flag as image PDF when ≥70% of pages are essentially
        # rasterized (no meaningful text + has images). Prevents "one scan page + lots of
        # text pages" being forced into pixel-only diff. ceil (not int) so the threshold
        # never rounds DOWN below 70% — e.g. a 2-page PDF needs BOTH pages rasterized
        # (ceil(1.4)=2), not just one (int(1.4)=1 = 50%), which would hide text diffs.
        is_image_pdf = total_pages > 0 and image_pages >= max(1, math.ceil(0.7 * total_pages))

        markdown_lines = [paragraph.text for paragraph in paragraphs]
        markdown = "\n\n".join(markdown_lines)
        return ParsedDocument(
            pages=len(doc),
            paragraphs=paragraphs,
            tables=[],
            # Parsed paragraphs already retain every text/bbox needed downstream.
            # Keeping every rawdict page here doubled peak memory for no consumer.
            raw_json={
                "engine": "pymupdf",
                "page_count": total_pages,
                "is_image_pdf": is_image_pdf,
                "table_candidate_count": table_candidates,
                "table_probe_errors": table_probe_errors,
            },
            markdown_text=markdown or None,
            is_image_pdf=is_image_pdf,
        )


def _parse_via_pdftotext(pdf_path: Path) -> ParsedDocument:
    command = ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"]
    proc = subprocess.run(command, capture_output=True, text=True, check=True)
    text = proc.stdout or ""

    pages_raw = text.split("\f")
    if pages_raw and not pages_raw[-1].strip():
        pages_raw = pages_raw[:-1]

    paragraphs: list[ParsedParagraph] = []
    for page_index, page_text in enumerate(pages_raw, start=1):
        lines = [line.rstrip() for line in page_text.splitlines() if line.strip()]
        for line_index, line in enumerate(lines):
            paragraphs.append(
                ParsedParagraph(
                    text=line.strip(),
                    bbox=_synthetic_paragraph_bbox(page_index, line_index, len(lines)),
                )
            )

    return ParsedDocument(
        pages=max(len(pages_raw), 1),
        paragraphs=paragraphs,
        tables=[],
        raw_json={"engine": "pdftotext", "raw_preview": text[:3000]},
        markdown_text=text or None,
    )


def _parse_via_ocr(pdf_path: Path, dpi: int = 200) -> ParsedDocument:
    with tempfile.TemporaryDirectory(prefix="pdf_ocr_") as temp_dir:
        prefix = Path(temp_dir) / "page"
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), str(prefix)],
            check=True,
            capture_output=True,
            text=True,
        )

        images = sorted(Path(temp_dir).glob("page-*.png"))
        if not images:
            raise RuntimeError("No page images generated for OCR")

        paragraphs: list[ParsedParagraph] = []
        raw_snippets: list[str] = []
        for page_idx, image in enumerate(images, start=1):
            proc = subprocess.run(
                ["tesseract", str(image), "stdout", "-l", "eng", "--psm", "6"],
                check=True,
                capture_output=True,
                text=True,
            )
            ocr_text = proc.stdout or ""
            raw_snippets.append(ocr_text[:1200])
            lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
            for line_index, line in enumerate(lines):
                paragraphs.append(
                    ParsedParagraph(
                        text=line,
                        bbox=_synthetic_paragraph_bbox(page_idx, line_index, len(lines)),
                    )
                )

        markdown = "\n\n".join(paragraph.text for paragraph in paragraphs)
        return ParsedDocument(
            pages=len(images),
            paragraphs=paragraphs,
            tables=[],
            raw_json={"engine": "ocr_tesseract", "raw_preview": "\n".join(raw_snippets)[:3000]},
            markdown_text=markdown or None,
        )


def _parse_table_via_mineru(
    pdf_path: Path,
    page_sizes: dict[int, tuple[float, float]],
) -> ParsedDocument:
    return _parse_via_mineru(pdf_path, page_sizes)


def _parse_table_via_docling(
    pdf_path: Path,
    _page_sizes: dict[int, tuple[float, float]],
) -> ParsedDocument:
    return _parse_via_docling(pdf_path)


def _parse_table_via_opendataloader(
    pdf_path: Path,
    _page_sizes: dict[int, tuple[float, float]],
) -> ParsedDocument:
    return _parse_via_opendataloader(pdf_path)


_TABLE_ENGINE_PARSERS = {
    "mineru": _parse_table_via_mineru,
    "docling": _parse_table_via_docling,
    "opendataloader": _parse_table_via_opendataloader,
}


def _attempt_table_engine(
    engine: str,
    pdf_path: Path,
    page_sizes: dict[int, tuple[float, float]],
    attempts: list[dict],
) -> ParsedDocument | None:
    trace: dict = {"engine": engine, "status": "running"}
    attempts.append(trace)
    started_at = time.perf_counter()
    try:
        parser = _TABLE_ENGINE_PARSERS.get(engine)
        if parser is None:  # pragma: no cover - internal guard
            raise ValueError(f"Unknown table parser engine: {engine}")
        with _heavy_parser_slot(trace):
            parsed = parser(pdf_path, page_sizes)
        trace["elapsed_seconds"] = round(time.perf_counter() - started_at, 4)
        trace["table_count"] = len(parsed.tables)
        trace["status"] = "candidate" if parsed.tables else "no_tables"
        return parsed if parsed.tables else None
    except Exception as exc:
        trace["elapsed_seconds"] = round(time.perf_counter() - started_at, 4)
        trace["status"] = "error"
        trace["error"] = f"{type(exc).__name__}: {exc}"[:500]
        return None


def _select_table_document(
    pdf_path: Path,
    page_sizes: dict[int, tuple[float, float]],
) -> tuple[ParsedDocument | None, dict]:
    from config import settings

    mineru_url = settings.mineru_api_url or os.getenv("MINERU_API_URL", "")
    strategy = settings.table_parser_strategy
    attempts: list[dict] = []
    routing = {
        "table_strategy": strategy,
        "table_engine": None,
        "attempts": attempts,
    }

    if strategy == "docling_first":
        order = ["docling"] + (["mineru"] if mineru_url else [])
    elif strategy == "mineru_first":
        order = (["mineru"] if mineru_url else []) + ["docling"]
    elif strategy == "opendataloader_first":
        order = ["opendataloader", "docling"] + (["mineru"] if mineru_url else [])
    else:
        # Legacy A/B mode only. The deterministic strategies above are the
        # optimized defaults because Python cannot cancel an already-running
        # Docling/MinerU thread safely after the other result wins.
        from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

        engines = ["docling"] + (["mineru"] if mineru_url else [])
        pool = ThreadPoolExecutor(max_workers=len(engines), thread_name_prefix="table-parser")
        futures = {
            pool.submit(_attempt_table_engine, engine, pdf_path, page_sizes, attempts): engine
            for engine in engines
        }
        selected = None
        pending = set(futures)
        try:
            while pending and selected is None:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    candidate = future.result()
                    if candidate and candidate.tables:
                        selected = candidate
                        routing["table_engine"] = futures[future]
                        break
            for future in pending:
                future.cancel()
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if selected:
            for attempt in attempts:
                if attempt["engine"] == routing["table_engine"] and attempt["status"] == "candidate":
                    attempt["status"] = "selected"
                    break
        return selected, routing

    for engine in order:
        candidate = _attempt_table_engine(engine, pdf_path, page_sizes, attempts)
        if candidate:
            routing["table_engine"] = engine
            attempts[-1]["status"] = "selected"
            return candidate, routing
    return None, routing


def _attach_routing(document: ParsedDocument, routing: dict) -> ParsedDocument:
    raw_json = dict(document.raw_json or {})
    raw_json["text_engine"] = raw_json.get("engine", "unknown")
    raw_json["table_engine"] = routing.get("table_engine")
    raw_json["routing"] = routing
    return ParsedDocument(
        pages=document.pages,
        paragraphs=document.paragraphs,
        tables=document.tables,
        raw_json=raw_json,
        markdown_text=document.markdown_text,
        is_image_pdf=document.is_image_pdf,
    )


def _parse_pdf_uncached(pdf_path: Path) -> ParsedDocument:
    errors: list[str] = []

    # PyMuPDF reads the embedded text layer directly. Image PDFs return early so
    # the established pixel-first guardrails remain unchanged.
    try:
        doc = _parse_via_fitz(pdf_path)
        if doc.is_image_pdf:
            return _attach_routing(
                doc,
                {
                    "document_type": "image",
                    "table_strategy": "skipped_image_pdf",
                    "table_engine": None,
                    "attempts": [],
                },
            )
        if doc.paragraphs:
            from config import settings

            table_candidate_count = int(doc.raw_json.get("table_candidate_count") or 0)
            table_probe_errors = int(doc.raw_json.get("table_probe_errors") or 0)
            if (
                settings.enable_lightweight_table_probe
                and table_candidate_count == 0
                and table_probe_errors == 0
            ):
                return _attach_routing(
                    doc,
                    {
                        "document_type": "digital",
                        "table_strategy": "skipped_no_table_candidate",
                        "table_engine": None,
                        "table_candidate_count": 0,
                        "attempts": [],
                    },
                )
            page_sizes = _get_page_sizes_fitz(pdf_path)
            table_doc, routing = _select_table_document(pdf_path, page_sizes)
            routing["document_type"] = "digital"
            routing["table_candidate_count"] = table_candidate_count
            if table_doc and table_doc.tables:
                doc = ParsedDocument(
                    pages=doc.pages,
                    paragraphs=doc.paragraphs,
                    tables=table_doc.tables,
                    raw_json=doc.raw_json,
                    markdown_text=doc.markdown_text,
                    is_image_pdf=False,
                )
            return _attach_routing(doc, routing)
    except ModuleNotFoundError as exc:
        errors.append(f"pymupdf unavailable: {exc}")
    except Exception as exc:  # pragma: no cover
        errors.append(f"pymupdf failed: {exc}")

    for engine, parser in (
        ("docling", _parse_via_docling),
        ("pdftotext", _parse_via_pdftotext),
        ("ocr_tesseract", _parse_via_ocr),
    ):
        try:
            parsed = parser(pdf_path)
            if engine != "pdftotext" or parsed.paragraphs:
                return _attach_routing(
                    parsed,
                    {
                        "document_type": "fallback",
                        "table_strategy": "fallback_chain",
                        "table_engine": engine if parsed.tables else None,
                        "attempts": [{"engine": engine, "status": "selected"}],
                    },
                )
            errors.append("pdftotext extracted no text")
        except FileNotFoundError as exc:
            errors.append(f"{engine} dependency missing: {exc}")
        except Exception as exc:  # pragma: no cover
            errors.append(f"{engine} failed: {exc}")

    detail = " | ".join(errors) if errors else "unknown parser error"
    raise RuntimeError(f"Failed to parse PDF '{pdf_path}': {detail}")


def parse_pdf(file_path: str) -> ParsedDocument:
    pdf_path = Path(file_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    from config import settings

    if not settings.enable_parser_cache:
        return _with_cache_status(_parse_pdf_uncached(pdf_path), hit=False)

    cache_key = _parser_cache_key(pdf_path)
    with _PARSE_CACHE_LOCK:
        cached = _PARSE_CACHE.get(cache_key)
        if cached is not None:
            _PARSE_CACHE.move_to_end(cache_key)
            return _with_cache_status(cached, hit=True)
        inflight = _PARSE_INFLIGHT.get(cache_key)
        if inflight is None:
            inflight = threading.Event()
            _PARSE_INFLIGHT[cache_key] = inflight
            is_owner = True
        else:
            is_owner = False

    if not is_owner:
        inflight.wait()
        with _PARSE_CACHE_LOCK:
            cached = _PARSE_CACHE.get(cache_key)
            if cached is not None:
                _PARSE_CACHE.move_to_end(cache_key)
                return _with_cache_status(cached, hit=True)
        # The owner failed before caching; retry normally and surface the real error.
        return _with_cache_status(_parse_pdf_uncached(pdf_path), hit=False)

    try:
        parsed = _with_cache_status(_parse_pdf_uncached(pdf_path), hit=False)
        with _PARSE_CACHE_LOCK:
            _PARSE_CACHE[cache_key] = parsed
            _PARSE_CACHE.move_to_end(cache_key)
            while len(_PARSE_CACHE) > max(1, int(settings.parser_cache_max_entries)):
                _PARSE_CACHE.popitem(last=False)
        return parsed
    finally:
        with _PARSE_CACHE_LOCK:
            event = _PARSE_INFLIGHT.pop(cache_key, None)
            if event:
                event.set()


def parse_pdf_fallback(file_path: str) -> ParsedDocument:
    """Fallback parser hook using pdftotext directly."""
    return _parse_via_pdftotext(Path(file_path))


def parse_image_pdf_via_mineru_ocr(file_path: str) -> ParsedDocument:
    """Parse an image-only PDF through MinerU with forced OCR.

    Used by the text-recall layer (diff_service.diff_positioned_paragraphs) to
    recover CJK block / rate-table changes the pixel path misses. Paragraph
    bboxes are scaled from MinerU's 0–1000 space using the real page size.
    Raises if MinerU is unavailable so the caller can degrade gracefully.
    """
    pdf_path = Path(file_path)
    page_sizes = _get_page_sizes_fitz(pdf_path)
    trace = {"engine": "mineru_ocr", "status": "running"}
    started_at = time.perf_counter()
    with _heavy_parser_slot(trace):
        parsed = _parse_via_mineru(pdf_path, page_sizes, parse_method="ocr")
    trace["elapsed_seconds"] = round(time.perf_counter() - started_at, 4)
    trace["status"] = "selected"
    return _attach_routing(
        parsed,
        {
            "document_type": "image_ocr",
            "table_strategy": "forced_mineru_ocr",
            "table_engine": "mineru",
            "attempts": [trace],
        },
    )


def render_markdown(document: ParsedDocument, source_name: str | None = None) -> str:
    if document.markdown_text and document.markdown_text.strip():
        if source_name:
            return f"# {source_name}\n\n{document.markdown_text.strip()}\n"
        return document.markdown_text.strip() + "\n"

    lines: list[str] = []
    if source_name:
        lines.append(f"# {source_name}")
        lines.append("")

    by_page: dict[int, list[str]] = {}
    for paragraph in document.paragraphs:
        by_page.setdefault(paragraph.bbox.page, []).append(paragraph.text.strip())

    for page in sorted(by_page):
        lines.append(f"## Page {page}")
        lines.append("")
        for paragraph_text in by_page[page]:
            if paragraph_text:
                lines.append(paragraph_text)
                lines.append("")

    return "\n".join(lines).strip() + "\n"


def save_markdown(document: ParsedDocument, output_path: Path, source_name: str | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = render_markdown(document, source_name=source_name)
    output_path.write_text(content, encoding="utf-8")
    return output_path
