from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from models.diff_models import BBox

if TYPE_CHECKING:
    from services.parser_service import ParsedParagraph

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_DIGIT_RE = re.compile(r"\d+")
_DIGIT_SEP_RE = re.compile(r"(?<=\d)[.,](?=\d)")
_FORMULA_NOISE_RE = re.compile(r"[\u2211\u222b\u220f\u221a\u222e]")
_ELLIPSIS = "..."


@dataclass(frozen=True)
class AlignmentDiff:
    kind: str
    old_text: str | None
    new_text: str | None
    old_bbox: BBox | None
    new_bbox: BBox | None
    confidence: float
    reason: str


@dataclass(frozen=True)
class _AlignedSequence:
    text: str
    raw_chars: list[str]
    bboxes: list[BBox | None]


@dataclass
class _ChangeGroup:
    old_start: int
    old_end: int
    new_start: int
    new_end: int


def _norm_char(ch: str) -> str:
    return unicodedata.normalize("NFKC", ch)


def _recall_norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if not ch.isspace())
    return _DIGIT_SEP_RE.sub("", text)


def _digits(text: str) -> tuple[str, ...]:
    return tuple(sorted(_DIGIT_RE.findall(_recall_norm(text))))


def _cjk_count(text: str) -> int:
    return len(_CJK_RE.findall(text))


def _clip(text: str | None, max_len: int = 180) -> str | None:
    if not text:
        return None
    return text[:max_len] + _ELLIPSIS if len(text) > max_len else text


def _sort_key(item: tuple[int, ParsedParagraph]) -> tuple[int, float, float, int]:
    index, paragraph = item
    bbox = paragraph.bbox
    if not bbox:
        return (10**9, 0.0, 0.0, index)
    return (bbox.page, -bbox.y1, bbox.x0, index)


def _build_sequence(paragraphs: list[ParsedParagraph]) -> _AlignedSequence:
    chars: list[str] = []
    raw_chars: list[str] = []
    bboxes: list[BBox | None] = []

    ordered = sorted(enumerate(paragraphs), key=_sort_key)
    for _, paragraph in ordered:
        char_bboxes = paragraph.char_bboxes or []
        for idx, raw_ch in enumerate(paragraph.text or ""):
            norm = _norm_char(raw_ch)
            if not norm or norm.isspace():
                continue
            bbox = char_bboxes[idx] if idx < len(char_bboxes) else paragraph.bbox
            for norm_ch in norm:
                if norm_ch.isspace():
                    continue
                chars.append(norm_ch)
                raw_chars.append(raw_ch)
                bboxes.append(bbox)

    return _AlignedSequence(text="".join(chars), raw_chars=raw_chars, bboxes=bboxes)


def _union_bbox(bboxes: list[BBox | None]) -> BBox | None:
    present = [bbox for bbox in bboxes if bbox]
    if not present:
        return None

    page_counts = Counter(bbox.page for bbox in present)
    page = page_counts.most_common(1)[0][0]
    same_page = [bbox for bbox in present if bbox.page == page]
    return BBox(
        page=page,
        x0=min(bbox.x0 for bbox in same_page),
        y0=min(bbox.y0 for bbox in same_page),
        x1=max(bbox.x1 for bbox in same_page),
        y1=max(bbox.y1 for bbox in same_page),
    )


def _slice_text(seq: _AlignedSequence, start: int, end: int) -> str:
    return "".join(seq.raw_chars[start:end])


def _change_groups(
    old_text: str,
    new_text: str,
    *,
    merge_equal_chars: int = 6,
) -> list[_ChangeGroup]:
    matcher = SequenceMatcher(None, old_text, new_text, autojunk=False)
    groups: list[_ChangeGroup] = []
    current: _ChangeGroup | None = None

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            if (
                current
                and i2 - i1 <= merge_equal_chars
                and j2 - j1 <= merge_equal_chars
            ):
                current.old_end = i2
                current.new_end = j2
            elif current:
                groups.append(current)
                current = None
            continue

        if current is None:
            current = _ChangeGroup(i1, i2, j1, j2)
        else:
            current.old_end = i2
            current.new_end = j2

    if current:
        groups.append(current)
    return groups


def _classify(old_text: str, new_text: str) -> tuple[bool, str, float]:
    old_norm = _recall_norm(old_text)
    new_norm = _recall_norm(new_text)
    if old_norm == new_norm:
        return False, "same_after_recall_norm", 0.0
    if _FORMULA_NOISE_RE.search(old_text) or _FORMULA_NOISE_RE.search(new_text):
        return False, "formula_noise", 0.0

    old_digits = _digits(old_text)
    new_digits = _digits(new_text)
    if old_digits != new_digits:
        return True, "number_change", 0.78

    max_len = max(len(old_norm), len(new_norm))
    if max_len < 3:
        return False, "too_short", 0.0

    if not old_norm and _cjk_count(new_text) >= 8:
        return True, "large_cjk_added", 0.70
    if not new_norm and _cjk_count(old_text) >= 8:
        return True, "large_cjk_deleted", 0.70

    return False, "wording_only_or_ocr_noise", 0.0


def align_paragraphs(
    old_paragraphs: list[ParsedParagraph],
    new_paragraphs: list[ParsedParagraph],
) -> list[AlignmentDiff]:
    """Shadow sequence alignment for OCR paragraphs.

    This is intentionally not wired into `diff_service.generate_diff_report`.
    It provides a text-first comparison path for regression experiments where
    MinerU re-segments the same visual text into different paragraph boxes.
    """
    old_seq = _build_sequence(old_paragraphs)
    new_seq = _build_sequence(new_paragraphs)
    if not old_seq.text and not new_seq.text:
        return []

    diffs: list[AlignmentDiff] = []
    for group in _change_groups(old_seq.text, new_seq.text):
        old_text = _slice_text(old_seq, group.old_start, group.old_end)
        new_text = _slice_text(new_seq, group.new_start, group.new_end)
        keep, reason, confidence = _classify(old_text, new_text)
        if not keep:
            continue

        if old_text and new_text:
            kind = "modified"
        elif new_text:
            kind = "added"
        else:
            kind = "deleted"

        diffs.append(AlignmentDiff(
            kind=kind,
            old_text=_clip(old_text),
            new_text=_clip(new_text),
            old_bbox=_union_bbox(old_seq.bboxes[group.old_start:group.old_end]),
            new_bbox=_union_bbox(new_seq.bboxes[group.new_start:group.new_end]),
            confidence=confidence,
            reason=reason,
        ))

    return diffs
