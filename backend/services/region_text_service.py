"""Verify image-PDF wording with column-aware, located, repeated OCR reads.

Local pixel crops are candidates, not proof that two different strings replace
one another. Read their surrounding column, align text independently of position,
and require agreement across two raster scales before recovering long additions.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import subprocess
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from difflib import SequenceMatcher
from statistics import median
from types import SimpleNamespace

from models.diff_models import BBox, DiffEvidence, DiffItem, DiffType
from services.pymupdf_guard import pymupdf_serialized

_CJK = re.compile(r"[\u3400-\u9fff]")


def key(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


@dataclass(frozen=True)
class Glyph:
    text: str
    box: BBox
    score: float
    line: tuple


def _union(glyphs):
    return BBox(page=glyphs[0].box.page, x0=min(g.box.x0 for g in glyphs),
                y0=median(g.box.y0 for g in glyphs)-1, x1=max(g.box.x1 for g in glyphs),
                y1=median(g.box.y1 for g in glyphs)+1)


def parse_tsv(tsv, *, page, rect, height, zoom):
    glyphs = []
    last_right = {}
    segments = defaultdict(int)
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not (text := key(row.get("text"))):
            continue
        score = max(0., float(row["conf"])) / 100
        left = rect.x0 + float(row["left"]) / zoom
        top = rect.y0 + float(row["top"]) / zoom
        width, h = float(row["width"]) / zoom, float(row["height"]) / zoom
        raw_line = (row["block_num"], row["par_num"], row["line_num"])
        if raw_line in last_right and left-last_right[raw_line] > 6:
            segments[raw_line] += 1
        last_right[raw_line] = left+width
        line = (*raw_line, segments[raw_line])
        for i, char in enumerate(text):
            glyphs.append(Glyph(char, BBox(page=page, x0=left + width*i/len(text),
                x1=left + width*(i+1)/len(text), y0=height-top-h, y1=height-top), score, line))
    return glyphs


def _text(glyphs):
    return "".join(g.text for g in glyphs)


@pymupdf_serialized
def _raster(page, rect, zoom):
    import fitz
    import numpy as np
    from PIL import Image

    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, colorspace=fitz.csGRAY)
    raster = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    # Light text on a dark coloured panel otherwise disappears in Tesseract's
    # global threshold. Isolate the bright ink; keep ordinary light pages intact.
    bright_ink = float(np.median(raster)) < 200 and float((raster > 220).mean()) < .5
    if bright_ink:
        buffer = io.BytesIO()
        Image.fromarray(np.where(raster > 215, 0, 255).astype(np.uint8)).save(buffer, "PNG")
        png = buffer.getvalue()
    else:
        png = pix.tobytes("png")
    return png


def _read_tsv(png, *, models, psm=6, lang="chi_tra+eng"):
    from services.persistent_cache import canonical_cache_key, load_json, save_json

    cache_key = canonical_cache_key("region-text", {
        "algorithm": "column-consensus-v1", "raster": hashlib.sha256(png).hexdigest(),
        "models": models, "lang": lang, "psm": psm,
    })
    cached = load_json("region_text", cache_key)
    if cached is None:
        result = subprocess.run(["tesseract", "stdin", "stdout", "-l", lang, "--psm", str(psm), "tsv"],
            input=png, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            env={**os.environ, "OMP_THREAD_LIMIT": "1", "OMP_NUM_THREADS": "1"})
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace")[:160])
        tsv = result.stdout.decode("utf-8")
        if not tsv.startswith("level\t"):
            raise ValueError("invalid region OCR response")
        # Validate the response before persisting it. This worker owns bytes and
        # Python data only; all PyMuPDF objects stay on the caller's thread.
        parse_tsv(tsv, page=1, rect=SimpleNamespace(x0=0, y0=0), height=1, zoom=1)
        save_json("region_text", cache_key, {"tsv": tsv})
        return tsv, False
    return cached["tsv"], True


def _count_read(stats, hit):
    name = "region_text_cache_hits" if hit else "region_text_ocr_calls"
    stats[name] = stats.get(name, 0)+1


@pymupdf_serialized
def _read(page, rect, *, zoom, models, stats, psm=6, lang="chi_tra+eng"):
    tsv, hit = _read_tsv(_raster(page, rect, zoom), models=models, psm=psm, lang=lang)
    _count_read(stats, hit)
    return parse_tsv(tsv, page=page.number+1, rect=rect, height=page.rect.height, zoom=zoom)


@pymupdf_serialized
def _read_pair(old_page, new_page, rect, *, zoom, models, stats):
    pages = (old_page, new_page)
    rects = [rect & p.rect for p in pages]
    payloads = [_raster(p, r, zoom) for p, r in zip(pages, rects)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        reads = list(pool.map(lambda png: _read_tsv(png, models=models), payloads))
    result = []
    for p, r, (tsv, hit) in zip(pages, rects, reads):
        _count_read(stats, hit)
        result.append(parse_tsv(tsv, page=p.number+1, rect=r, height=p.rect.height, zoom=zoom))
    return result


@pymupdf_serialized
def _vertical_rules(page, rect):
    import cv2
    import fitz
    import numpy as np

    zoom = 2
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, colorspace=fitz.csGRAY)
    raster = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    # A dark coloured panel is a solid background, not hundreds of rules.
    # Horizontal closing isolates only thin dark strokes against neighbours.
    contrast = cv2.morphologyEx(raster, cv2.MORPH_BLACKHAT, np.ones((1, 11), np.uint8))
    mask = (contrast > 20).astype(np.uint8)
    rules = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((70, 1), np.uint8))
    xs = np.flatnonzero(rules.sum(axis=0) > max(90, pix.height*.25))
    groups = []
    for x in xs:
        if not groups or x - groups[-1][-1] > 5:
            groups.append([int(x)])
        else:
            groups[-1].append(int(x))
    # Wide solid panels are not table rules.
    return [rect.x0+sum(g)/len(g)/zoom for g in groups if len(g) <= 12]


@pymupdf_serialized
def _regions(items, old_page, new_page):
    import fitz

    regions = []
    for item in items:
        if "control/version" in item.context:
            continue
        box = item.new_bbox or item.old_bbox
        if not box or box.page != old_page.number+1:
            continue
        w, h = box.x1-box.x0, box.y1-box.y0
        has_words = len(_CJK.findall((item.old_value or "")+(item.new_value or ""))) >= 8
        if not has_words and (w < 130 or h < 55):
            continue
        pad_y = 48 if h < 70 else 8
        rect = fitz.Rect(max(0, box.x0-12), max(0, old_page.rect.height-box.y1-pad_y),
                         min(old_page.rect.width, box.x1+12), min(old_page.rect.height, old_page.rect.height-box.y0+pad_y))
        scan = fitz.Rect(rect.x0-65, rect.y0, rect.x1+65, rect.y1) & old_page.rect
        rules = sorted(set(round(x, 0) for p in (old_page, new_page) for x in _vertical_rules(p, scan & p.rect)))
        merged = []
        for x in rules:
            if not merged or x-merged[-1] > 4:
                merged.append(x)
        relevant = [x for x in merged if rect.x0-65 <= x <= rect.x1+65]
        inside = [x for x in relevant if rect.x0+10 < x < rect.x1-10]
        boundaries = [rect.x0, *inside, rect.x1]
        if len(inside) == 0 and len(relevant) >= 2:
            left = [x for x in relevant if x <= (box.x0+box.x1)/2]
            right = [x for x in relevant if x > (box.x0+box.x1)/2]
            if left and right and 55 <= min(right)-max(left) <= 330:
                boundaries = [max(left), min(right)]
        for left, right in zip(boundaries, boundaries[1:]):
            if right-left >= 65:
                regions.append(fitz.Rect(left+3, rect.y0, right-3, rect.y1))
    kept = []
    for rect in sorted(regions, key=lambda r: r.get_area(), reverse=True):
        if not any((rect & other).get_area() >= rect.get_area()*.9 for other in kept):
            kept.append(rect)
    return kept[:6]


def _substantial(text):
    return len(_CJK.findall(text)) >= 12 or bool(re.search(r"\d{10,}", text))


def _mixed_list_items(text):
    markers = re.findall(r"[（(]\d{1,2}[）)]|(?:^|[。；;])\d{1,2}[.、]", text)
    return len(markers) > 1


def _word_key(text):
    return re.sub(r"[^A-Za-z0-9\u3400-\u9fff.%+-]", "", key(text))


def _near_existing(text, documents):
    """Only veto speculative additions; never erase a small real text edit."""
    needle = _word_key(text)
    for document in documents:
        haystack = _word_key(document)
        if needle in haystack:
            return True
        matcher = SequenceMatcher(None, needle, haystack, autojunk=False)
        for match in matcher.get_matching_blocks():
            if match.size < 5:
                continue
            offset = match.b-match.a
            for shift in (-4, 0, 4):
                start = max(0, offset+shift)
                for extra in (-4, 0, 4):
                    window = haystack[start:start+len(needle)+extra]
                    if SequenceMatcher(None, needle, window, autojunk=False).ratio() >= .82:
                        return True
    return False


def _ends_existing_line(prefix, glyphs):
    lines = []
    for glyph in glyphs:
        if not lines or glyph.line != lines[-1][0]:
            lines.append([glyph.line, ""])
        lines[-1][1] += glyph.text
    target = _word_key(prefix)
    return any(_word_key(text).endswith(target) and (
        i == len(lines)-1 or re.match(r"[（(]?\d+[.)、]", lines[i+1][1])
    ) for i, (_, text) in enumerate(lines))


def _appended_line_context(source, cursor, opposite, confirm):
    start = cursor
    while start > 0 and source[start-1].line == source[cursor].line:
        start -= 1
    prefix = _word_key(_text(source[start:cursor]))
    for trim in range(4):
        candidate = prefix[:len(prefix)-trim] if trim else prefix
        if len(candidate) >= 8 and _ends_existing_line(candidate, opposite) and _ends_existing_line(candidate, confirm):
            return True
    return False


def _paragraph_start(source, cursor):
    start = cursor
    while start > 0 and source[start-1].line == source[cursor].line:
        start -= 1
    before = _text(source[start:cursor])
    marker = r"(?:[（(]?\d{1,2}[.)、）]|[★☆※*]|[【\[]註[】\]])"
    if re.fullmatch(marker, before) or re.match(marker, _text(source[cursor:cursor+5])):
        return True
    if before or start == 0:
        return False
    previous = start-1
    while previous > 0 and source[previous-1].line == source[start-1].line:
        previous -= 1
    return bool(re.search(r"[。！？!?；;]$", _text(source[previous:start])))


def confirmed_additions(source, confirm, opposite, opposite_confirm):
    """Long novel spans, agreed at two scales, between unchanged text anchors.

    This deliberately does not turn every OCR mismatch into an addition. Reflow,
    short near-glyph replacements, units and numeric edits stay with local OCR.
    """
    a, b = _text(opposite), _text(source)
    c, d = _text(confirm), _text(opposite_confirm)
    old_references = set(re.findall(r"\d{10,}", a+d))
    edits = [op for op in SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if op[0] != "equal"]
    runs = []
    for match in SequenceMatcher(None, b, c, autojunk=False).get_matching_blocks():
        start, end = match.a, match.a+match.size
        cursor = start
        while cursor < end:
            stop = cursor+1
            while stop < end and source[stop].line == source[cursor].line:
                stop += 1
            text = b[cursor:stop]
            agrees = confirm[match.b+cursor-start:match.b+stop-start]
            scores = [max(x.score, y.score) for x, y in zip(source[cursor:stop], agrees)]
            novel = [(tag, i, j, max(k, cursor), min(l, stop)) for tag, i, j, k, l in edits if min(l, stop)-max(k, cursor) >= 8]
            new_reference = (any(number not in old_references for number in re.findall(r"\d{10,}", text))
                             and all(number in b or number in c for number in old_references))
            if (_substantial(text) and not _mixed_list_items(text) and scores and sum(scores)/len(scores) >= .85
                    and sum(score < .55 for score in scores) <= len(scores)*.12
                    and text not in a and text not in d and novel and (new_reference or not _near_existing(text, (a, d)))):
                # A nearly matching old sentence is OCR drift, not a new clause.
                old_lines = defaultdict(str)
                for variant, glyphs in enumerate((opposite, opposite_confirm)):
                    for glyph in glyphs:
                        old_lines[(variant, *glyph.line)] += glyph.text
                if new_reference or max((SequenceMatcher(None, text, s, autojunk=False).ratio() for s in old_lines.values()), default=0) < .82:
                    changed_start, changed_end = min(e[3] for e in novel), max(e[4] for e in novel)
                    prefix = 0
                    for i in range(min(30, len(text)), 7, -1):
                        if text[:i] in a and text[:i] in d:
                            prefix = i
                            break
                    if prefix and b.count(text[:prefix]) > 1:
                        prefix = 0
                    if prefix and not (_ends_existing_line(text[:prefix], opposite) and _ends_existing_line(text[:prefix], opposite_confirm)):
                        prefix = 0
                    # Require unchanged context on both sides, or a literal
                    # suffix appended to an existing line. OCR omissions at a
                    # crop edge cannot justify a new paragraph.
                    before = SequenceMatcher(None, a, b[:changed_start], autojunk=False).find_longest_match()
                    after = SequenceMatcher(None, a, b[changed_end:], autojunk=False).find_longest_match()
                    appended = _appended_line_context(source, cursor, opposite, opposite_confirm)
                    anchored = (before.size >= 12 and after.size >= 12) or prefix >= 8 or appended
                    paragraph = new_reference or appended or prefix >= 8 or _paragraph_start(source, cursor)
                    if anchored and paragraph and _substantial(text[prefix:]):
                        runs.append((text, _union(source[cursor:stop]), text[:prefix] or None))
            cursor = stop
    return runs


def _supported(text, glyphs):
    normalized = key(text)
    document = _text(glyphs)
    if normalized in document:
        return True
    # Cropped marker/ASCII garbage may precede a real clause. Compare its
    # substantive CJK runs without treating a single missing glyph as equal.
    phrases = re.findall(r"[\u3400-\u9fff]{8,}", normalized)
    return bool(phrases) and all(phrase in document for phrase in phrases)


def _may_need_recovery(a, b):
    for source, opposite in ((a, b), (b, a)):
        other = _text(opposite)
        runs, current = [], []
        for glyph in source:
            if glyph.score < .35 or (current and current[-1].line != glyph.line):
                if current:
                    runs.append(_text(current))
                    current = []
            if glyph.score >= .35:
                current.append(glyph)
        if current:
            runs.append(_text(current))
        if any(_substantial(text) and (not _near_existing(text, (other,))
               or any(number not in other for number in re.findall(r"\d{10,}", text))) for text in runs):
            return True
    return False


def _spatial_text(glyphs):
    rows = []
    seen = set()
    for glyph in sorted(glyphs, key=lambda g: (-(g.box.y0+g.box.y1)/2, g.box.x0)):
        identity = (glyph.text, round(glyph.box.x0), round((glyph.box.y0+glyph.box.y1)/2))
        if identity in seen:
            continue
        seen.add(identity)
        center = (glyph.box.y0+glyph.box.y1)/2
        row = next((row for row in rows[-3:] if abs(row[0]-center) < 3), None)
        if row is None:
            rows.append([center, [glyph]])
        else:
            row[1].append(glyph)
    return "".join(_text(sorted(row, key=lambda g: g.box.x0)) for _, row in rows)


@pymupdf_serialized
def _reconcile_regions_uncached(items, old_path, new_path, *, stats, warnings):
    import fitz
    from services.evidence_service import runtime_model_manifest

    models = runtime_model_manifest()
    recovered = []
    verified = []
    page_reads = defaultdict(lambda: [[], []])
    with fitz.open(old_path) as old, fitz.open(new_path) as new:
        for page_num in sorted({(i.new_bbox or i.old_bbox).page for i in items if i.new_bbox or i.old_bbox}):
            if page_num > min(len(old), len(new)):
                continue
            po, pn = old[page_num-1], new[page_num-1]
            for rect in _regions(items, po, pn):
                try:
                    a, b = _read_pair(po, pn, rect, zoom=300/72, models=models, stats=stats)
                    page_reads[page_num][0].extend(a)
                    page_reads[page_num][1].extend(b)
                    local_claims = any(i.diff_type != DiffType.IMAGE_DIFF and "control/version" not in i.context
                        and len(_CJK.findall((i.old_value or "")+(i.new_value or ""))) >= 8
                        and (loc := (i.new_bbox or i.old_bbox)) and loc.page == page_num
                        and loc.x0 < rect.x1 and loc.x1 > rect.x0
                        and po.rect.height-loc.y1 < rect.y1 and po.rect.height-loc.y0 > rect.y0 for i in items)
                    if not local_claims and not _may_need_recovery(a, b):
                        stats["region_text_secondary_reads_skipped"] = stats.get("region_text_secondary_reads_skipped", 0)+2
                        continue
                    aa, bb = _read_pair(po, pn, rect, zoom=400/72, models=models, stats=stats)
                except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
                    warnings.append(f"region_text_error: {type(exc).__name__}")
                    continue
                box = BBox(page=page_num, x0=rect.x0, y0=po.rect.height-rect.y1, x1=rect.x1, y1=po.rect.height-rect.y0)
                verified.append((box, a, b, aa, bb))
                for source, confirm, opposite, opposite_confirm, reverse in ((b, bb, a, aa, False), (a, aa, b, bb, True)):
                    for text, location, prefix in confirmed_additions(source, confirm, opposite, opposite_confirm):
                        text = text.rstrip("©®™")
                        if location.x1 >= rect.x1-5 and not re.search(r"[。；;）)]$", text):
                            stats["region_text_crop_edge_rejected"] = stats.get("region_text_crop_edge_rejected", 0)+1
                            continue
                        source_page = po if reverse else pn
                        check_rect = fitz.Rect(location.x0-3, source_page.rect.height-location.y1-2,
                                               location.x1+3, source_page.rect.height-location.y0+2) & source_page.rect
                        try:
                            focused = _read(source_page, check_rect, zoom=8, models=models, stats=stats, psm=7, lang="chi_tra")
                            if _word_key(text) not in _word_key(_text(focused)):
                                # Excessive enlargement can distort a small
                                # glyph. One bounded lower-scale read must still
                                # agree exactly; never fuzzy-correct the value.
                                focused = _read(source_page, check_rect, zoom=6, models=models, stats=stats, psm=7, lang="chi_tra")
                                stats["region_text_focused_retries"] = stats.get("region_text_focused_retries", 0)+1
                        except (OSError, ValueError, subprocess.SubprocessError, RuntimeError) as exc:
                            warnings.append(f"region_text_confirmation_error: {type(exc).__name__}")
                            continue
                        if _word_key(text) not in _word_key(_text(focused)):
                            stats["region_text_confirmation_rejected"] = stats.get("region_text_confirmation_rejected", 0)+1
                            continue
                        old_value, new_value = (prefix, text) if not reverse else (text, prefix)
                        item = DiffItem(id="", diff_type=DiffType.TEXT_MODIFIED if prefix else (DiffType.DELETED if reverse else DiffType.ADDED),
                            old_value=old_value, new_value=new_value,
                            old_bbox=location if reverse or prefix else None,
                            new_bbox=location if not reverse or prefix else None,
                            context=f"Page {page_num} 區塊文字內容變更", confidence=.85,
                            decision_reason="column_aligned_two_scale_text_agreement",
                            evidence=[DiffEvidence(source="region_text", kind="text_modified" if prefix else ("deleted" if reverse else "added"),
                                old_value=old_value, new_value=new_value,
                                old_bbox=location if reverse or prefix else None,
                                new_bbox=location if not reverse or prefix else None,
                                confidence=.85, metadata={"two_scale_agreement": True, "focused_read_confirmed": True,
                                                          "confidence_kind": "ocr_agreement_heuristic"})])
                        if not any((i.old_value, i.new_value) == (old_value, new_value) and (i.new_bbox or i.old_bbox).page == page_num for i in recovered):
                            recovered.append(item)
    # A table's columns can cut a note spanning the whole row. Reassemble the
    # independently read columns by physical line before calling any span new.
    # Fuzzy matching only vetoes speculative recovery; it never removes a real
    # local single-character/numeric candidate.
    accepted_recovery = []
    for item in recovered:
        location = item.new_bbox or item.old_bbox
        old_page_text, new_page_text = (_spatial_text(gs) for gs in page_reads[location.page])
        text, opposite, source = (item.old_value, new_page_text, old_page_text) if item.diff_type == DiffType.DELETED else (item.new_value, old_page_text, new_page_text)
        old_refs = set(re.findall(r"\d{10,}", opposite))
        novel_reference = (any(n not in old_refs for n in re.findall(r"\d{10,}", text or ""))
                           and all(n in source for n in old_refs))
        if not novel_reference and _near_existing(text, (opposite,)):
            stats["region_text_existing_span_rejected"] = stats.get("region_text_existing_span_rejected", 0)+1
            continue
        accepted_recovery.append(item)
    recovered = accepted_recovery
    result = []
    for item in items:
        if item.diff_type == DiffType.IMAGE_DIFF or "control/version" in item.context or len(_CJK.findall((item.old_value or "")+(item.new_value or ""))) < 8:
            result.append(item)
            continue
        location = item.new_bbox or item.old_bbox
        regions = [r for r in verified if r[0].page == location.page and
                   min(r[0].x1, location.x1)-max(r[0].x0, location.x0) > (location.x1-location.x0)*.7 and
                   min(r[0].y1, location.y1)-max(r[0].y0, location.y0) > (location.y1-location.y0)*.7]
        if not regions:
            result.append(item)
            continue
        moved = any(_supported(item.old_value, r[2]+r[4]) and _supported(item.new_value, r[1]+r[3]) for r in regions)
        if moved:
            stats["region_text_moved_claims_removed"] = stats.get("region_text_moved_claims_removed", 0)+1
            continue
        # A cropped string must also be present in its own larger-scale read.
        supported = any(_supported(item.old_value, r[1]+r[3]) and _supported(item.new_value, r[2]+r[4]) for r in regions)
        if supported:
            result.append(item)
        else:
            visual = item.model_copy(deep=True)
            visual.diff_type = DiffType.IMAGE_DIFF
            visual.old_value = visual.new_value = None
            visual.context = f"Page {location.page} 待確認文字區域"
            visual.decision_reason = "local_ocr_not_confirmed_by_column_reads"
            visual.evidence = [DiffEvidence(source="pixel_diff", kind="visual_region", old_bbox=item.old_bbox,
                new_bbox=item.new_bbox, confidence=.85, metadata={"unconfirmed_local_ocr": True})]
            result.append(visual)
            stats["region_text_unconfirmed_claims"] = stats.get("region_text_unconfirmed_claims", 0)+1
    stats["region_text_recovered"] = len(recovered)
    return result+recovered


@pymupdf_serialized
def reconcile_regions(items, old_path, new_path, *, stats, warnings):
    import json
    from pathlib import Path
    from services.diff_service import _pixel_cache_file_hash
    from services.evidence_service import runtime_model_manifest
    from services.persistent_cache import canonical_cache_key, load_json, save_json

    if not items:
        return items
    cache_key = canonical_cache_key("region-reconciliation", {
        "source": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "old": _pixel_cache_file_hash(old_path), "new": _pixel_cache_file_hash(new_path),
        "input": hashlib.sha256(json.dumps([i.model_dump() for i in items], sort_keys=True).encode()).hexdigest(),
        "models": runtime_model_manifest(),
    })
    cached = load_json("region_reconciliation", cache_key)
    if cached is not None:
        stats.update(cached["stats"])
        stats["region_text_ocr_calls"] = 0
        stats["region_reconciliation_cache_hit"] = True
        return [DiffItem.model_validate(item) for item in cached["items"]]
    previous_warnings = len(warnings)
    result = _reconcile_regions_uncached(items, old_path, new_path, stats=stats, warnings=warnings)
    if len(warnings) == previous_warnings:
        save_json("region_reconciliation", cache_key, {
            "items": [item.model_dump() for item in result],
            "stats": {name: value for name, value in stats.items() if name.startswith("region_text_")},
        })
    return result
