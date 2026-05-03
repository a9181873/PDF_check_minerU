import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import zip_longest

from models.diff_models import DiffItem, DiffType, BBox
from services.parser_service import ParsedDocument, ParsedParagraph, ParsedTable

NUMBER_PATTERN = re.compile(r"\d+(?:\.\d+)?%?")

# Characters that should be stripped or unified before comparison to prevent
# false-positive diffs caused by font encoding quirks, ligature substitutions,
# non-printing Unicode, and typographic variants common in Taiwanese insurance PDFs.
_STRIP_TABLE = str.maketrans("", "", (
    "\u00AD"  # soft hyphen
    "\u200B"  # zero-width space
    "\u200C"  # zero-width non-joiner
    "\u200D"  # zero-width joiner
    "\uFEFF"  # BOM / zero-width no-break space
    "\u2060"  # word joiner
))

_UNIFY_TABLE = str.maketrans(
    "\u00A0\u202F\u2009\u2008\u2007\u2006\u2005\u2004\u2003\u2002",  # various spaces
    "          ",  # replace all with regular space
)

_DASH_RE = re.compile(r"[\u2013\u2014\u2015\u2212\uFE58\uFE63\uFF0D]")  # en/em/minus → -


def _deep_normalize(text: str) -> str:
    """Aggressive normalization to suppress PDF-rendering artefacts."""
    # NFKC handles ligatures (ﬁ→fi, ﬂ→fl), full/half-width, compatibility variants
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_STRIP_TABLE)
    text = text.translate(_UNIFY_TABLE)
    text = _DASH_RE.sub("-", text)
    return " ".join(text.split())


def _normalize(text: str) -> str:
    return _deep_normalize(text)

def refine_bbox_for_text(full_text: str, full_bbox, start_idx: int, end_idx: int):
    if not full_text or end_idx <= start_idx or not full_bbox:
        return full_bbox
    height = full_bbox.y1 - full_bbox.y0
    if height > 25:
        # Multiline, interpolation will be stretched
        return full_bbox
    length = len(full_text)
    frac_start = start_idx / length
    frac_end = end_idx / length
    width = full_bbox.x1 - full_bbox.x0
    from models.diff_models import BBox
    return BBox(
        page=full_bbox.page,
        x0=full_bbox.x0 + width * frac_start,
        y0=full_bbox.y0,
        x1=full_bbox.x0 + width * frac_end,
        y1=full_bbox.y1
    )

def _contains_number(text: str | None) -> bool:
    if not text:
        return False
    return bool(NUMBER_PATTERN.search(text))

def is_meaningful_diff(old_val: str | None, new_val: str | None) -> bool:
    v1 = _deep_normalize(old_val or "")
    v2 = _deep_normalize(new_val or "")
    return v1 != v2


def _guess_diff_type(old_value: str | None, new_value: str | None) -> DiffType:
    if old_value and new_value:
        if _contains_number(old_value) or _contains_number(new_value):
            return DiffType.NUMBER_MODIFIED
        return DiffType.TEXT_MODIFIED
    if old_value and not new_value:
        return DiffType.DELETED
    return DiffType.ADDED


@dataclass
class TextToken:
    text: str
    paragraph: ParsedParagraph
    start_char_idx: int
    end_char_idx: int

def _tokenize_paragraphs(paragraphs: list[ParsedParagraph]) -> list[TextToken]:
    tokens = []
    # Tokenize: group English words and numbers (with commas/dots), split everything else (CJK, punctuation) into single characters.
    # This completely eliminates false-positive diffs caused by spacing or attached punctuation.
    for p in paragraphs:
        for match in re.finditer(r'[a-zA-Z0-9.,]+|\S', p.text):
            tokens.append(TextToken(
                text=match.group(0),
                paragraph=p,
                start_char_idx=match.start(),
                end_char_idx=match.end()
            ))
    return tokens

def _group_tokens_by_paragraph(tokens: list[TextToken]) -> list[list[TextToken]]:
    if not tokens:
        return []
    groups = []
    current_group = [tokens[0]]
    for t in tokens[1:]:
        if t.paragraph is current_group[-1].paragraph:
            current_group.append(t)
        else:
            groups.append(current_group)
            current_group = [t]
    groups.append(current_group)
    return groups

def _get_bbox_for_token_group(group: list[TextToken]) -> tuple[str, BBox | None]:
    if not group:
        return "", None
    p = group[0].paragraph
    full_text = p.text
    full_bbox = p.bbox
    start_idx = group[0].start_char_idx
    end_idx = group[-1].end_char_idx
    
    sub_text = full_text[start_idx:end_idx]
    
    if not full_bbox:
        return sub_text, None
        
    height = full_bbox.y1 - full_bbox.y0
    if height > 35:
        # multiline wrap heavily compromises linear interpolation
        return sub_text, full_bbox
        
    length = max(len(full_text), 1)
    
    # NEW: Try character-level precise bounding boxes if available
    if p.char_bboxes and len(p.char_bboxes) == length:
        relevant_chars = p.char_bboxes[start_idx:end_idx]
        if relevant_chars:
            x0 = min(c.x0 for c in relevant_chars)
            y0 = min(c.y0 for c in relevant_chars)
            x1 = max(c.x1 for c in relevant_chars)
            y1 = max(c.y1 for c in relevant_chars)
            return sub_text, BBox(page=full_bbox.page, x0=x0, y0=y0, x1=x1, y1=y1)

    # Fallback to linear interpolation for non-char-mapped paragraphs
    frac_start = start_idx / length
    frac_end = end_idx / length
    width = full_bbox.x1 - full_bbox.x0
    refined_bbox = BBox(
        page=full_bbox.page,
        x0=full_bbox.x0 + width * frac_start,
        y0=full_bbox.y0,
        x1=full_bbox.x0 + width * frac_end,
        y1=full_bbox.y1
    )
    return sub_text, refined_bbox

def diff_paragraphs(
    old_paragraphs: list[ParsedParagraph],
    new_paragraphs: list[ParsedParagraph],
) -> list[DiffItem]:
    old_tokens = _tokenize_paragraphs(old_paragraphs)
    new_tokens = _tokenize_paragraphs(new_paragraphs)

    old_words = [_deep_normalize(t.text) for t in old_tokens]
    new_words = [_deep_normalize(t.text) for t in new_tokens]

    matcher = SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    diff_items: list[DiffItem] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue

        old_slice = old_tokens[i1:i2]
        new_slice = new_tokens[j1:j2]
        
        old_groups = _group_tokens_by_paragraph(old_slice)
        new_groups = _group_tokens_by_paragraph(new_slice)
        
        paired_count = max(len(old_groups), len(new_groups))
        
        for idx in range(paired_count):
            og = old_groups[idx] if idx < len(old_groups) else []
            ng = new_groups[idx] if idx < len(new_groups) else []
            
            old_str, old_bbox = _get_bbox_for_token_group(og)
            new_str, new_bbox = _get_bbox_for_token_group(ng)
            
            if not is_meaningful_diff(old_str, new_str):
                continue
                
            dtype = _guess_diff_type(old_str if old_str else None, new_str if new_str else None)
            
            page_ctx = []
            if og and og[0].paragraph.bbox: page_ctx.append(f"Page {og[0].paragraph.bbox.page}")
            if ng and ng[0].paragraph.bbox: page_ctx.append(f"Page {ng[0].paragraph.bbox.page}")
            ctx = " / ".join(set(page_ctx)) if page_ctx else "N/A"
            
            diff_items.append(
                DiffItem(
                    id="",
                    diff_type=dtype,
                    old_value=old_str if old_str else None,
                    new_value=new_str if new_str else None,
                    old_bbox=old_bbox,
                    new_bbox=new_bbox,
                    context=ctx,
                    confidence=0.85,
                )
            )

    return diff_items


def align_table_headers(old_df, new_df) -> tuple[dict, dict]:
    old_cols = {col: col for col in old_df.columns}
    new_cols = {col: col for col in new_df.columns}
    return old_cols, new_cols


def _normalize_cell(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else _normalize(text)


def _table_context(table: ParsedTable, index: int) -> str:
    caption = (table.caption or "").strip()
    if caption:
        return f"Table {index} ({caption}) on Page {table.bbox.page}"
    return f"Table {index} on Page {table.bbox.page}"


def _table_dataframe_rows(table: ParsedTable) -> list[list[str]]:
    df = table.dataframe.copy()
    if df.empty and len(df.columns) == 0:
        return []

    df.columns = [_normalize_cell(col) for col in df.columns]
    rows: list[list[str]] = []
    header = [_normalize_cell(col) for col in df.columns]
    if any(header):
        rows.append(header)

    for _, row in df.iterrows():
        rows.append([_normalize_cell(value) for value in row.tolist()])
    return rows


# When ≥70% of cells in a table differ, collapse to a single whole-table diff
# item instead of flooding the UI with hundreds of individual cell markers.
_CELL_DIFF_AGGREGATE_THRESHOLD = 0.70


def _diff_table_cells(
    old_table: ParsedTable,
    new_table: ParsedTable,
    context: str,
) -> list[DiffItem]:
    """Return cell-level DiffItems for a matched old/new table pair."""
    old_rows = _table_dataframe_rows(old_table)
    new_rows = _table_dataframe_rows(new_table)

    old_col_count = max(len(r) for r in old_rows) if old_rows else 0
    new_col_count = max(len(r) for r in new_rows) if new_rows else 0
    total_cells = max(
        len(old_rows) * old_col_count,
        len(new_rows) * new_col_count,
    )
    changed_cells = 0
    pending: list[DiffItem] = []

    for row_index, (old_row, new_row) in enumerate(
        zip_longest(old_rows, new_rows, fillvalue=[]),
        start=1,
    ):
        for col_index, (old_cell, new_cell) in enumerate(
            zip_longest(old_row, new_row, fillvalue=""),
            start=1,
        ):
            if old_cell == new_cell:
                continue

            old_val = old_cell or None
            new_val = new_cell or None
            if not is_meaningful_diff(old_val, new_val):
                continue
            changed_cells += 1
            o_cell_bbox = old_table.cell_bboxes.get((row_index - 1, col_index - 1))
            n_cell_bbox = new_table.cell_bboxes.get((row_index - 1, col_index - 1))
            pending.append(DiffItem(
                id="",
                diff_type=_guess_diff_type(old_val, new_val),
                old_value=old_val,
                new_value=new_val,
                old_bbox=o_cell_bbox,
                new_bbox=n_cell_bbox,
                context=f"{context} / row {row_index} col {col_index}",
                confidence=0.72,
            ))

    if not pending:
        return []

    # Aggregation: if most cells changed, one whole-table marker is clearer.
    change_ratio = changed_cells / max(total_cells, 1)
    if change_ratio >= _CELL_DIFF_AGGREGATE_THRESHOLD:
        return [DiffItem(
            id="",
            diff_type=DiffType.TEXT_MODIFIED,
            old_value=f"{context} 整表替換（{changed_cells}/{total_cells} 格變更）",
            new_value=f"{context} 整表替換（{changed_cells}/{total_cells} 格變更）",
            old_bbox=old_table.bbox,
            new_bbox=new_table.bbox,
            context=f"{context} — 整表替換",
            confidence=0.80,
        )]

    return pending


def diff_tables(old_tables: list[ParsedTable], new_tables: list[ParsedTable]) -> list[DiffItem]:
    diff_items: list[DiffItem] = []

    for table_index, (old_table, new_table) in enumerate(
        zip_longest(old_tables, new_tables),
        start=1,
    ):
        if old_table and not new_table:
            context = _table_context(old_table, table_index)
            diff_items.append(DiffItem(
                id="",
                diff_type=DiffType.DELETED,
                old_value=f"{context} removed",
                new_value=None,
                old_bbox=old_table.bbox,
                new_bbox=None,
                context=context,
                confidence=0.8,
            ))
            continue

        if new_table and not old_table:
            context = _table_context(new_table, table_index)
            diff_items.append(DiffItem(
                id="",
                diff_type=DiffType.ADDED,
                old_value=None,
                new_value=f"{context} added",
                old_bbox=None,
                new_bbox=new_table.bbox,
                context=context,
                confidence=0.8,
            ))
            continue

        if not old_table or not new_table:
            continue

        context = _table_context(new_table, table_index)
        diff_items.extend(_diff_table_cells(old_table, new_table, context))

    return diff_items


def diff_pixels(
    old_pdf_path: str,
    new_pdf_path: str,
    threshold: int = 30,
    min_area: int = 400,
    dpi: int = 200,
) -> list[DiffItem]:
    """Pixel-level diff using PyMuPDF rendering + numpy + scipy connected components.

    Designed for image-only PDFs that have no text layer. Renders each page at
    `dpi` resolution, computes per-pixel absolute difference, applies morphological
    dilation to merge nearby changed pixels into regions, then converts each region
    back to PDF point coordinates for the overlay system.
    """
    try:
        import fitz
        import numpy as np
        from scipy import ndimage
    except ImportError as exc:
        return []

    try:
        doc_old = fitz.open(old_pdf_path)
        doc_new = fitz.open(new_pdf_path)
    except Exception:
        return []

    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    scale_to_pt = 72.0 / dpi
    struct = ndimage.generate_binary_structure(2, 2)
    items: list[DiffItem] = []

    try:
        n_old = len(doc_old)
        n_new = len(doc_new)
        shared = min(n_old, n_new)

        # Flag entire pages as added/deleted when page counts differ
        for page_i in range(shared, max(n_old, n_new)):
            page_no = page_i + 1
            if page_i < n_old:
                page = doc_old[page_i]
                bbox = BBox(page=page_no, x0=0, y0=0, x1=page.rect.width, y1=page.rect.height)
                items.append(DiffItem(
                    id="", diff_type=DiffType.DELETED,
                    old_value=f"Page {page_no} removed", new_value=None,
                    old_bbox=bbox, new_bbox=None,
                    context=f"Page {page_no} 整頁刪除", confidence=0.99,
                ))
            else:
                page = doc_new[page_i]
                bbox = BBox(page=page_no, x0=0, y0=0, x1=page.rect.width, y1=page.rect.height)
                items.append(DiffItem(
                    id="", diff_type=DiffType.ADDED,
                    old_value=None, new_value=f"Page {page_no} added",
                    old_bbox=None, new_bbox=bbox,
                    context=f"Page {page_no} 整頁新增", confidence=0.99,
                ))

        def _words_in_rect(words_list, rect):
            """Collect words that INTERSECT with rect.
            Uses intersection (not center-point) so that long Chinese
            spans whose bbox is wider than the diff region are captured.
            """
            result = []
            for w in words_list:
                if rect.intersects(fitz.Rect(w[:4])):
                    result.append(w[4])
            return " ".join(result).strip()

        for page_i in range(shared):
            page_no = page_i + 1
            page_old = doc_old[page_i]
            page_new = doc_new[page_i]
            ph_pt = page_old.rect.height  # PDF page height in points

            # Pre-extract all words with coordinates for text-overlap suppression
            old_words = page_old.get_text("words")  # [(x0,y0,x1,y1,"word",...), ...]
            new_words = page_new.get_text("words")

            pix_old = page_old.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
            pix_new = page_new.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)

            arr_old = np.frombuffer(pix_old.samples, dtype=np.uint8).reshape(
                pix_old.height, pix_old.width
            )
            arr_new = np.frombuffer(pix_new.samples, dtype=np.uint8).reshape(
                pix_new.height, pix_new.width
            )

            diff = np.abs(arr_old.astype(np.int16) - arr_new.astype(np.int16))
            mask = diff > threshold

            if not mask.any():
                continue

            # Morphological dilation merges pixels within ~4px proximity
            dilated = ndimage.binary_dilation(mask, structure=struct, iterations=4)
            labeled, n_regions = ndimage.label(dilated)

            for rid in range(1, n_regions + 1):
                region = labeled == rid
                actual_px = int((mask & region).sum())
                if actual_px < min_area:
                    continue
                # Suppress noise: require at least 2% of the region to differ
                region_total = int(region.sum())
                if region_total > 0 and actual_px / region_total < 0.02:
                    continue

                rows, cols = np.where(region)
                r0, r1 = int(rows.min()), int(rows.max()) + 1
                c0, c1 = int(cols.min()), int(cols.max()) + 1

                # Structural-similarity filter: when the bounding box is nearly
                # identical on both sides (e.g. the same raster image re-encoded
                # with slightly different JPEG settings or DPI), the region is
                # rendering noise rather than a content change. NCC is scale and
                # brightness invariant, so it stays close to 1.0 under pure
                # compression/gamma drift but drops sharply for real edits.
                patch_old = arr_old[r0:r1, c0:c1].astype(np.float64)
                patch_new = arr_new[r0:r1, c0:c1].astype(np.float64)
                if patch_old.size >= 100:
                    # Apply a light Gaussian blur to make the comparison robust against
                    # tiny anti-aliasing shifts or sub-pixel kerning differences
                    patch_old_b = ndimage.gaussian_filter(patch_old, sigma=1.0)
                    patch_new_b = ndimage.gaussian_filter(patch_new, sigma=1.0)
                    
                    # Shift-Invariant NCC: search for the best alignment within +/- 5 pixels.
                    # This suppresses identical text that was slightly moved by the designer
                    # without needing to fall back to the error-prone OCR engine.
                    h, w = patch_old_b.shape
                    best_ncc = -1.0
                    
                    # Sort shifts by distance from center so we find exact matches immediately
                    max_shift = 5
                    shifts = [(dy, dx) for dy in range(-max_shift, max_shift+1) for dx in range(-max_shift, max_shift+1)]
                    shifts.sort(key=lambda s: s[0]**2 + s[1]**2)
                    
                    for dy, dx in shifts:
                        r_o_start, r_o_end = max(0, -dy), min(h, h - dy)
                        c_o_start, c_o_end = max(0, -dx), min(w, w - dx)
                        r_n_start, r_n_end = max(0, dy), min(h, h + dy)
                        c_n_start, c_n_end = max(0, dx), min(w, w + dx)
                        
                        slice_o = patch_old_b[r_o_start:r_o_end, c_o_start:c_o_end]
                        slice_n = patch_new_b[r_n_start:r_n_end, c_n_start:c_n_end]
                        
                        if slice_o.size < 50:
                            continue
                            
                        std_o = float(slice_o.std())
                        std_n = float(slice_n.std())
                        if std_o < 1.0 or std_n < 1.0:
                            continue
                            
                        ncc = float(
                            ((slice_o - slice_o.mean()) * (slice_n - slice_n.mean())).mean()
                            / (std_o * std_n)
                        )
                        if ncc > best_ncc:
                            best_ncc = ncc
                        
                        # Threshold for "identical text just shifted"
                        if best_ncc > 0.94:
                            break
                            
                    if best_ncc > 0.94:
                        continue

                # PDF points in fitz's top-left origin (Y grows down)
                fx0 = float(c0) * scale_to_pt
                fx1 = float(c1 - 1) * scale_to_pt
                fy0 = float(r0) * scale_to_pt
                fy1 = float(r1 - 1) * scale_to_pt
                # BBox model stores bottom-left origin
                bbox = BBox(
                    page=page_no,
                    x0=fx0,
                    y0=ph_pt - fy1,
                    x1=fx1,
                    y1=ph_pt - fy0,
                )

                # ── Frame + Bone strategy (Two-Tier) ─────────────────────
                # Frame = pixel diff region (定位：哪裡有改變)
                # Bone Tier 1 = native PDF text layer (fast path)
                # Bone Tier 2 = targeted local OCR on cropped patch (fallback
                #               for "outline-text" PDFs where designers ran
                #               "Create Outlines" before export, making all
                #               glyphs vector paths with zero text layer).
                fitz_rect = fitz.Rect(fx0, fy0, fx1, fy1)
                search_rect = fitz_rect + (-3, -3, 3, 3)

                ot = _words_in_rect(old_words, search_rect)
                nt = _words_in_rect(new_words, search_rect)

                # ── Tier 1: native text layer comparison ──────────────────
                if ot and nt:
                    on = _deep_normalize(ot)
                    nn = _deep_normalize(nt)
                    if on and nn and on == nn:
                        continue  # identical text → rendering noise, suppress

                # ── Tier 2: local OCR fallback (outline-text PDFs) ────────
                # Triggered when NEITHER side has a native text layer in the
                # diff region.
                #
                # IMPORTANT: Large regions (tables, complex layouts) should NOT
                # be OCR'd — Tesseract produces garbage on structured tables.
                # Instead, report them as visual diffs with screenshots only.
                patch_w = c1 - c0
                patch_h = r1 - r0
                patch_area = patch_w * patch_h
                # Require both width and height > 40px to prevent flagging thin grid lines as large regions
                is_large_region = patch_area > 8000 and patch_w > 40 and patch_h > 40

                # If there's no native text AND it's just a thin graphic line, it's rendering noise
                if not ot and not nt and (patch_h < 20 or patch_w < 20):
                    continue

                if not ot and not nt:
                    try:
                        import subprocess, tempfile, os as _os
                        from PIL import Image as _PILImage, ImageFilter as _PILFilter

                        # Render only the diff patch at 3× DPI for OCR clarity
                        clip_rect = fitz.Rect(fx0, fy0, fx1, fy1)
                        ocr_mat = fitz.Matrix(3.0, 3.0)

                        pix_o = page_old.get_pixmap(matrix=ocr_mat, clip=clip_rect, colorspace=fitz.csGRAY)
                        pix_n = page_new.get_pixmap(matrix=ocr_mat, clip=clip_rect, colorspace=fitz.csGRAY)

                        def _ocr_patch(pix) -> str:
                            """Run Tesseract on a fitz Pixmap with binarization preprocessing."""
                            pil_img = _PILImage.frombytes("L", (pix.width, pix.height), pix.samples)
                            # Scale up to at least 120px tall for Tesseract accuracy
                            if pil_img.height < 120:
                                scale = max(1, 120 // pil_img.height + 1)
                                pil_img = pil_img.resize(
                                    (pil_img.width * scale, pil_img.height * scale),
                                    _PILImage.LANCZOS,
                                )
                            # Otsu-style binarization
                            pil_arr = np.array(pil_img)
                            thresh = int(pil_arr.mean()) - 20
                            thresh = max(80, min(thresh, 200))
                            pil_img = _PILImage.fromarray(
                                ((pil_arr > thresh) * 255).astype(np.uint8)
                            )
                            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                                pil_img.save(f.name)
                                tmp_path = f.name
                            try:
                                result = subprocess.run(
                                    ["tesseract", tmp_path, "stdout",
                                     "-l", "chi_tra",
                                     "--psm", "6",
                                     "--oem", "1"],
                                    capture_output=True, text=True, timeout=10,
                                )
                                return result.stdout.strip()
                            except Exception:
                                return ""
                            finally:
                                try:
                                    _os.unlink(tmp_path)
                                except Exception:
                                    pass

                        ocr_old_raw = _ocr_patch(pix_o)
                        ocr_new_raw = _ocr_patch(pix_n)

                        ocr_old_norm = _deep_normalize(ocr_old_raw)
                        ocr_new_norm = _deep_normalize(ocr_new_raw)

                        # Strict space-immune comparison
                        old_stripped = ocr_old_norm.replace(" ", "") if ocr_old_norm else ""
                        new_stripped = ocr_new_norm.replace(" ", "") if ocr_new_norm else ""

                        if old_stripped and new_stripped and old_stripped == new_stripped:
                            continue

                        # Only use OCR results if BOTH sides produced text.
                        if ocr_old_raw and ocr_new_raw:
                            ot = ocr_old_raw
                            nt = ocr_new_raw

                    except Exception:
                        pass  # OCR unavailable or timed out → fall through

                # ── Report: text diff or pure graphic diff ─────────────────
                old_text: str | None = None
                new_text: str | None = None
                diff_type = DiffType.IMAGE_DIFF
                context_label = f"Page {page_no} 圖形差異 ({actual_px:,} px)"

                if ot or nt:
                    MAX_LEN = 200
                    old_text = (ot[:MAX_LEN] + "…") if len(ot) > MAX_LEN else (ot or None)
                    new_text = (nt[:MAX_LEN] + "…") if len(nt) > MAX_LEN else (nt or None)
                    diff_type = DiffType.TEXT_MODIFIED
                    context_label = f"Page {page_no} 內容變更"
                elif is_large_region:
                    # Large region with no text = table/layout structural change.
                    # Report as IMAGE_DIFF WITH screenshots (don't suppress).
                    diff_type = DiffType.IMAGE_DIFF
                    context_label = f"Page {page_no} 表格/版面變更"

                # Only suppress SMALL graphic noise (lines, borders, anti-aliasing).
                # Large visual diffs (tables, layout) are meaningful and should be shown.
                if diff_type == DiffType.IMAGE_DIFF and not is_large_region:
                    continue

                try:
                    import base64, logging as _logging
                    clip_rect = fitz.Rect(fx0, fy0, fx1, fy1) + (-4, -4, 4, 4)
                    # Use 2x resolution for table/large regions, 1.5x for text
                    ui_scale = 2.0 if is_large_region else 1.5
                    mat_ui = fitz.Matrix(ui_scale, ui_scale)
                    p_o = page_old.get_pixmap(matrix=mat_ui, clip=clip_rect)
                    p_n = page_new.get_pixmap(matrix=mat_ui, clip=clip_rect)
                    b64_old = "data:image/png;base64," + base64.b64encode(p_o.tobytes("png")).decode("utf-8")
                    b64_new = "data:image/png;base64," + base64.b64encode(p_n.tobytes("png")).decode("utf-8")
                    _logging.info(f"[CROP] Generated base64 images: old={len(b64_old)}B, new={len(b64_new)}B for region {r0},{c0}-{r1},{c1}")
                except Exception as e:
                    import logging as _logging
                    _logging.error(f"[CROP] Failed to generate base64 for region {r0},{c0}-{r1},{c1}: {e}")
                    b64_old = None
                    b64_new = None

                items.append(
                    DiffItem(
                        id="",
                        diff_type=diff_type,
                        old_value=old_text,
                        new_value=new_text,
                        old_bbox=bbox,
                        new_bbox=bbox,
                        old_image_base64=b64_old,
                        new_image_base64=b64_new,
                        context=context_label,
                        confidence=0.95,
                    )
                )
    finally:
        doc_old.close()
        doc_new.close()

    return items


def diff_images(
    old_pdf_path: str,
    new_pdf_path: str,
) -> list[DiffItem]:
    """Compare embedded images across pages using perceptual hashing (pHash).

    Detects image replacements, additions, and deletions that text/pixel diff
    might miss or misattribute.
    """
    try:
        import fitz
        import imagehash
        from PIL import Image
    except ImportError:
        return []

    try:
        doc_old = fitz.open(old_pdf_path)
        doc_new = fitz.open(new_pdf_path)
    except Exception:
        return []

    items: list[DiffItem] = []

    def _extract_images(doc) -> list[list[dict]]:
        """Return per-page list of {xref, bbox, phash}."""
        pages: list[list[dict]] = []
        for page in doc:
            page_imgs: list[dict] = []
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n > 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    pil_img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                    phash = imagehash.phash(pil_img)
                except Exception:
                    continue
                # Find image bbox on page
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                r = rects[0]
                ph = page.rect.height
                pw = page.rect.width
                
                # Ignore full-page background images (e.g. >= 80% of page area)
                if (r.width * r.height) / (pw * ph) > 0.8:
                    continue
                    
                page_imgs.append({
                    "xref": xref,
                    "phash": phash,
                    "rect": r,
                    "bbox": BBox(page=page.number + 1, x0=r.x0, y0=ph - r.y1, x1=r.x1, y1=ph - r.y0),
                    "width": r.width,
                    "height": r.height,
                })
            pages.append(page_imgs)
        return pages

    def _iou(a, b) -> float:
        x0 = max(a.x0, b.x0)
        y0 = max(a.y0, b.y0)
        x1 = min(a.x1, b.x1)
        y1 = min(a.y1, b.y1)
        inter = max(0, x1 - x0) * max(0, y1 - y0)
        area_a = (a.x1 - a.x0) * (a.y1 - a.y0)
        area_b = (b.x1 - b.x0) * (b.y1 - b.y0)
        union = area_a + area_b - inter
        return inter / union if union > 0 else 0.0

    try:
        old_pages = _extract_images(doc_old)
        new_pages = _extract_images(doc_new)
        shared = min(len(old_pages), len(new_pages))

        for page_i in range(shared):
            page_no = page_i + 1
            old_imgs = old_pages[page_i]
            new_imgs = new_pages[page_i]
            matched_new: set[int] = set()

            for oi in old_imgs:
                best_j = -1
                best_iou = 0.0
                for j, ni in enumerate(new_imgs):
                    if j in matched_new:
                        continue
                    iou_val = _iou(oi["bbox"], ni["bbox"])
                    if iou_val > best_iou:
                        best_iou = iou_val
                        best_j = j

                if best_j >= 0 and best_iou >= 0.8:
                    matched_new.add(best_j)
                    ni = new_imgs[best_j]
                    hamming = oi["phash"] - ni["phash"]
                    size_changed = abs(oi["width"] - ni["width"]) > 2 or abs(oi["height"] - ni["height"]) > 2
                    
                    # Only report image change if hamming distance is significant (> 4) 
                    # or size changed, to ignore minor export artifacts
                    if hamming > 4 or size_changed:
                        desc_parts = []
                        if hamming > 0:
                            desc_parts.append(f"\u5716\u7247\u5167\u5bb9\u8b8a\u66f4 (hamming={hamming})")
                        if size_changed:
                            desc_parts.append(f"\u5c3a\u5bf8 {oi['width']:.0f}x{oi['height']:.0f} \u2192 {ni['width']:.0f}x{ni['height']:.0f}")
                        items.append(DiffItem(
                            id="", diff_type=DiffType.IMAGE_DIFF,
                            old_value="\u5d4c\u5165\u5716\u7247\u8b8a\u66f4",
                            new_value="; ".join(desc_parts),
                            old_bbox=oi["bbox"], new_bbox=ni["bbox"],
                            context=f"Page {page_no} \u5d4c\u5165\u5716\u7247\u8b8a\u66f4",
                            confidence=0.90,
                        ))
                else:
                    items.append(DiffItem(
                        id="", diff_type=DiffType.DELETED,
                        old_value=f"Page {page_no} \u5d4c\u5165\u5716\u7247\u522a\u9664",
                        new_value=None,
                        old_bbox=oi["bbox"], new_bbox=None,
                        context=f"Page {page_no} \u5716\u7247\u522a\u9664",
                        confidence=0.85,
                    ))

            for j, ni in enumerate(new_imgs):
                if j not in matched_new:
                    items.append(DiffItem(
                        id="", diff_type=DiffType.ADDED,
                        old_value=None,
                        new_value=f"Page {page_no} \u5d4c\u5165\u5716\u7247\u65b0\u589e",
                        old_bbox=None, new_bbox=ni["bbox"],
                        context=f"Page {page_no} \u5716\u7247\u65b0\u589e",
                        confidence=0.85,
                    ))
    finally:
        doc_old.close()
        doc_new.close()

    return items


def _sort_key(item: DiffItem) -> tuple[int, float]:
    bbox = item.new_bbox or item.old_bbox
    if not bbox:
        return (99999, 0.0)
    return (bbox.page, -bbox.y1)


def merge_diff_results(
    text_diffs: list[DiffItem],
    table_diffs: list[DiffItem],
    pixel_diffs: list[DiffItem] | None,
    image_diffs: list[DiffItem] | None = None,
) -> list[DiffItem]:
    merged = [*text_diffs, *table_diffs]
    if pixel_diffs:
        merged.extend(pixel_diffs)
    if image_diffs:
        merged.extend(image_diffs)

    # ── Deduplication: remove smaller boxes contained within larger ones ──
    # This prevents "框中有框" (box within box) where e.g. a table-level
    # diff overlaps with cell-level or pixel-level diffs inside it.
    def _get_bbox(item: DiffItem) -> BBox | None:
        return item.new_bbox or item.old_bbox

    def _contains(outer: BBox, inner: BBox) -> bool:
        """Check if outer bbox fully contains inner bbox (same page)."""
        if outer.page != inner.page:
            return False
        margin = 2.0  # tolerance in points
        return (outer.x0 - margin <= inner.x0 and
                outer.y0 - margin <= inner.y0 and
                outer.x1 + margin >= inner.x1 and
                outer.y1 + margin >= inner.y1)

    def _area(b: BBox) -> float:
        return max(0, b.x1 - b.x0) * max(0, b.y1 - b.y0)

    if len(merged) > 1:
        to_remove: set[int] = set()
        for i in range(len(merged)):
            if i in to_remove:
                continue
            bi = _get_bbox(merged[i])
            if not bi:
                continue
            for j in range(len(merged)):
                if j == i or j in to_remove:
                    continue
                bj = _get_bbox(merged[j])
                if not bj:
                    continue
                # If j is fully inside i, and i is larger, remove j
                if _contains(bi, bj) and _area(bi) > _area(bj) * 1.2:
                    to_remove.add(j)
        if to_remove:
            merged = [item for idx, item in enumerate(merged) if idx not in to_remove]

    merged = sorted(merged, key=_sort_key)
    for index, item in enumerate(merged, start=1):
        item.id = f"d{index:03d}"
    return merged


def generate_diff_report(
    project_id: str,
    old_filename: str,
    new_filename: str,
    old_doc: ParsedDocument,
    new_doc: ParsedDocument,
    old_pdf_path: str | None = None,
    new_pdf_path: str | None = None,
):
    from datetime import datetime, timezone

    from models.diff_models import DiffReport

    # Route to pixel diff when EITHER side lacks a text layer — text diff on a
    # one-sided text layer produces a flood of spurious ADDED/DELETED items.
    use_pixel_only = (old_doc.is_image_pdf or new_doc.is_image_pdf) and old_pdf_path and new_pdf_path

    # Embedded image comparison (always run when paths available)
    img_diffs: list[DiffItem] | None = None
    if old_pdf_path and new_pdf_path:
        try:
            img_diffs = diff_images(old_pdf_path, new_pdf_path)
        except Exception:
            img_diffs = None
    imgc = len(img_diffs) if img_diffs else 0

    if use_pixel_only:
        pixel_diffs = diff_pixels(old_pdf_path, new_pdf_path)
        merged_items = merge_diff_results([], [], pixel_diffs, img_diffs)
        mode = "image_pdf" if (old_doc.is_image_pdf and new_doc.is_image_pdf) else "mixed_pdf"
        summary = f"{mode}; pixel={len(pixel_diffs)}, img={imgc}"
    else:
        text_diffs = diff_paragraphs(old_doc.paragraphs, new_doc.paragraphs)
        table_diffs = diff_tables(old_doc.tables, new_doc.tables)
        # Always run pixel diff as supplementary for text PDFs, then
        # cross-verify: any pixel region where both sides' text is identical
        # is suppressed inside diff_pixels via the text identity check.
        pixel_diffs_fb = None
        if old_pdf_path and new_pdf_path:
            pixel_diffs_fb = diff_pixels(old_pdf_path, new_pdf_path)
        merged_items = merge_diff_results(text_diffs, table_diffs, pixel_diffs_fb, img_diffs)
        pxc = len(pixel_diffs_fb) if pixel_diffs_fb else 0
        summary = f"text_pdf; text={len(text_diffs)}, table={len(table_diffs)}, pixel={pxc}, img={imgc}"

    return DiffReport(
        project_id=project_id,
        old_filename=old_filename,
        new_filename=new_filename,
        created_at=datetime.now(timezone.utc).isoformat(),
        total_diffs=len(merged_items),
        items=merged_items,
        summary=summary,
    )
