from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from models.diff_models import DiffItem, DiffType

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_DIGIT_RE = re.compile(r"\d+")
_DATE_OR_DOC_RE = re.compile(
    r"(?:民國)?\d{2,3}年\d{1,2}月?\d{0,2}日?|第?\d{7,}號|Version|Control No|商品文?號",
    re.I,
)
_RATE_OR_AMOUNT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:%|元|美元)")
_PHONE_RE = re.compile(r"(?:0800[-\d]*|\(?0\d\)?[-\d]{6,})")


@dataclass(frozen=True)
class HybridRecallCandidate:
    item: DiffItem
    source_strategy: str
    hybrid_score: int
    hybrid_notes: list[str]


def _page(item: DiffItem) -> int | None:
    box = item.old_bbox or item.new_bbox
    return box.page if box else None


def _norm_text(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def _item_text(item: DiffItem) -> str:
    return " ".join(part for part in (item.old_value, item.new_value) if part)


def _cjk_count(text: str | None) -> int:
    return len(_CJK_RE.findall(text or ""))


def _digits(text: str | None) -> set[str]:
    return set(_DIGIT_RE.findall(_norm_text(text)))


def _has_high_value_number(text: str) -> bool:
    return bool(_RATE_OR_AMOUNT_RE.search(text) or _DATE_OR_DOC_RE.search(text))


def _has_phone(text: str) -> bool:
    return bool(_PHONE_RE.search(text))


def _is_customer_service_phone_fragment(text: str) -> bool:
    compact = _norm_text(text)
    if not _has_phone(compact):
        return False
    if not re.search(r"客服|服務專線|申訴電話|免費申訴", compact):
        return False
    return _cjk_count(compact) <= 12


def _is_long_cjk_added(item: DiffItem) -> bool:
    return item.diff_type == DiffType.ADDED and not item.old_value and _cjk_count(item.new_value) >= 25


def _looks_like_alignment_clause_fragment(item: DiffItem) -> bool:
    if "OCR對齊" not in item.context:
        return False
    old_cjk = _cjk_count(item.old_value)
    new_cjk = _cjk_count(item.new_value)
    if item.diff_type == DiffType.DELETED and old_cjk >= 25:
        return True
    if item.diff_type == DiffType.NUMBER_MODIFIED and min(old_cjk, new_cjk) <= 2 and max(old_cjk, new_cjk) >= 25:
        return True
    return False


def _score_recall_item(item: DiffItem, source_strategy: str) -> tuple[int, list[str]]:
    text = _item_text(item)
    notes: list[str] = []
    score = 50

    if item.diff_type == DiffType.NUMBER_MODIFIED:
        score += 20
        notes.append("number")
    elif item.diff_type in {DiffType.ADDED, DiffType.DELETED}:
        score += 10
        notes.append(item.diff_type.value)

    if _has_high_value_number(text):
        score += 18
        notes.append("high_value_number")
    elif re.search(r"\d", text):
        score += 8
        notes.append("digit")

    if _RATE_OR_AMOUNT_RE.search(text):
        score += 10
        notes.append("rate_or_amount")

    cjk = _cjk_count(text)
    if cjk >= 25:
        score += 20
        notes.append("long_cjk")
    elif cjk >= 12:
        score += 12
        notes.append("medium_cjk")

    if _has_phone(text):
        score += 8
        notes.append("phone")

    if _is_customer_service_phone_fragment(text):
        score -= 30
        notes.append("customer_service_fragment")

    if _looks_like_alignment_clause_fragment(item):
        score -= 20
        notes.append("alignment_clause_fragment")

    if source_strategy == "heuristic" and _is_long_cjk_added(item):
        score += 15
        notes.append("heuristic_long_added")

    return score, notes


def _duplicate_score(left: DiffItem, right: DiffItem) -> float:
    left_text = _norm_text(_item_text(left))
    right_text = _norm_text(_item_text(right))
    if not left_text or not right_text:
        return 0.0
    if _page(left) != _page(right):
        return 0.0
    if left.diff_type == right.diff_type and _has_high_value_number(left_text + right_text):
        left_digits = _digits(left_text)
        right_digits = _digits(right_text)
        if left_digits and right_digits:
            overlap = len(left_digits & right_digits) / min(len(left_digits), len(right_digits))
            if overlap >= 0.5:
                return 0.9
    if left_text in right_text or right_text in left_text:
        return min(len(left_text), len(right_text)) / max(len(left_text), len(right_text))
    return SequenceMatcher(None, left_text, right_text, autojunk=False).ratio()


def build_hybrid_recall_candidates(
    alignment_items: list[DiffItem],
    heuristic_items: list[DiffItem],
    *,
    min_score: int = 65,
) -> list[HybridRecallCandidate]:
    """Select reviewer-useful recall candidates from both OCR strategies."""
    preferred_clause_pages = {
        _page(item)
        for item in heuristic_items
        if _is_long_cjk_added(item)
    }

    candidates: list[HybridRecallCandidate] = []
    for source, items in (("alignment", alignment_items), ("heuristic", heuristic_items)):
        for item in items:
            if (
                source == "alignment"
                and _page(item) in preferred_clause_pages
                and (_looks_like_alignment_clause_fragment(item) or _cjk_count(_item_text(item)) >= 25)
            ):
                continue
            score, notes = _score_recall_item(item, source)
            if score < min_score:
                continue
            candidates.append(HybridRecallCandidate(item, source, score, notes))

    candidates.sort(key=lambda c: (-c.hybrid_score, _page(c.item) or 10**9, c.source_strategy))
    selected: list[HybridRecallCandidate] = []
    for candidate in candidates:
        if any(_duplicate_score(candidate.item, chosen.item) >= 0.72 for chosen in selected):
            continue
        selected.append(candidate)

    return sorted(selected, key=lambda c: (_page(c.item) or 10**9, -c.hybrid_score))


def build_hybrid_recall_items(alignment_items: list[DiffItem], heuristic_items: list[DiffItem]) -> list[DiffItem]:
    return [candidate.item for candidate in build_hybrid_recall_candidates(alignment_items, heuristic_items)]


def hybrid_candidate_to_dict(candidate: HybridRecallCandidate) -> dict[str, Any]:
    return {
        "source_strategy": candidate.source_strategy,
        "hybrid_score": candidate.hybrid_score,
        "hybrid_notes": candidate.hybrid_notes,
    }
