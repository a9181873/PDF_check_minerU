"""Canonical candidate regions, risk classification, and evidence provenance."""

from __future__ import annotations

import hashlib
import importlib.metadata
import os
import platform
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from models.diff_models import (
    AnalysisStage,
    BBox,
    CandidateRegion,
    DiffEvidence,
    DiffItem,
    DiffType,
    ReviewLane,
    RiskLevel,
)

_CRITICAL_FIELD_RE = re.compile(
    r"(?:%|％|利率|費率|金額|保費|保額|給付|版號|版本|version|control\s*no|文號|日期|年|月|日|元|美元)",
    re.IGNORECASE,
)
_TABLE_RE = re.compile(r"表格|費率表|試算表|整表|table", re.IGNORECASE)
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _bbox_signature(bbox: BBox | None) -> str:
    if bbox is None:
        return "-"
    # One-point quantisation keeps the identifier stable across tiny renderer drift.
    return ":".join(
        [
            str(bbox.page),
            *(str(round(value)) for value in (bbox.x0, bbox.y0, bbox.x1, bbox.y1)),
        ]
    )


def stable_candidate_id(item: DiffItem) -> str:
    bbox = item.new_bbox or item.old_bbox
    page = bbox.page if bbox else 0
    fallback = ""
    if bbox is None:
        fallback = "|".join(filter(None, (item.context, item.old_value, item.new_value)))
    raw = "|".join(
        [
            "candidate-v1",
            str(page),
            _bbox_signature(bbox),
            fallback,
        ]
    )
    return f"c-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _area(bbox: BBox | None) -> float:
    if not bbox:
        return 0.0
    return max(0.0, bbox.x1 - bbox.x0) * max(0.0, bbox.y1 - bbox.y0)


def candidate_region_for(item: DiffItem, candidate_id: str) -> CandidateRegion | None:
    bbox = item.new_bbox or item.old_bbox
    if not bbox:
        return None
    if item.diff_type == DiffType.IMAGE_DIFF:
        region_type = "table_or_layout" if _TABLE_RE.search(item.context or "") else "visual"
    else:
        region_type = item.diff_type.value
    return CandidateRegion(
        candidate_id=candidate_id,
        page=bbox.page,
        region_type=region_type,
        old_bbox=item.old_bbox,
        new_bbox=item.new_bbox,
        area_pt2=max(_area(item.old_bbox), _area(item.new_bbox)),
    )


def classify_risk(item: DiffItem) -> RiskLevel:
    joined = " ".join(filter(None, (item.context, item.old_value, item.new_value)))
    if item.diff_type == DiffType.NUMBER_MODIFIED or _CRITICAL_FIELD_RE.search(joined):
        return RiskLevel.CRITICAL
    if item.diff_type == DiffType.IMAGE_DIFF and _TABLE_RE.search(joined):
        return RiskLevel.HIGH
    if item.diff_type in {DiffType.ADDED, DiffType.DELETED}:
        cjk_count = len(_CJK_RE.findall(joined))
        return RiskLevel.HIGH if cjk_count >= 6 else RiskLevel.MEDIUM
    if item.diff_type == DiffType.TEXT_MODIFIED:
        return RiskLevel.HIGH
    return RiskLevel.MEDIUM


@lru_cache(maxsize=1)
def runtime_model_manifest() -> dict[str, str]:
    manifest = {
        "python": platform.python_version(),
        "platform": platform.machine(),
        "ocr_langs": os.getenv("OCR_LANGS", "chi_tra+chi_sim+eng"),
    }
    for package in ("PyMuPDF", "docling", "paddleocr"):
        try:
            manifest[package.lower()] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue

    try:
        result = subprocess.run(
            ["tesseract", "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        first_line = (result.stdout or result.stderr).splitlines()[0]
        manifest["tesseract"] = first_line.strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        pass

    try:
        result = subprocess.run(
            ["pdftoppm", "-v"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        first_line = (result.stdout or result.stderr).splitlines()[0]
        manifest["poppler"] = first_line.strip()
    except (OSError, subprocess.SubprocessError, IndexError):
        pass

    try:
        result = subprocess.run(
            ["tesseract", "--list-langs"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        location_match = re.search(r'in ["\']?(.+?)["\']? \(\d+\):', result.stdout)
        if location_match:
            tessdata_dir = Path(location_match.group(1))
            traineddata_hashes = []
            # Pixel OCR currently always invokes chi_tra and chi_tra+eng even
            # when OCR_LANGS is customized for another parser path. Hash the
            # union so a traineddata upgrade always invalidates pixel artifacts.
            ocr_languages = {
                language.strip()
                for language in manifest["ocr_langs"].split("+")
                if language.strip()
            }
            ocr_languages.update({"chi_tra", "eng"})
            manifest["pixel_ocr_model_langs"] = "+".join(sorted(ocr_languages))
            for language in sorted(ocr_languages):
                traineddata = tessdata_dir / f"{language}.traineddata"
                if not traineddata.is_file():
                    continue
                digest = hashlib.sha256()
                with traineddata.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                traineddata_hashes.append(f"{language}:{digest.hexdigest()[:16]}")
            if traineddata_hashes:
                manifest["tessdata_sha256"] = ",".join(traineddata_hashes)
    except (OSError, subprocess.SubprocessError):
        pass
    return manifest


def annotate_diff_items(
    items: list[DiffItem],
    *,
    stage: AnalysisStage,
    source: str = "primary_diff",
    model_manifest: dict[str, str] | None = None,
) -> list[DiffItem]:
    manifest = model_manifest or runtime_model_manifest()
    for item in items:
        candidate_id = item.candidate_id or stable_candidate_id(item)
        item.candidate_id = candidate_id
        item.candidate_region = item.candidate_region or candidate_region_for(item, candidate_id)
        item.review_lane = (
            ReviewLane.NEEDS_VISUAL_REVIEW
            if item.diff_type == DiffType.IMAGE_DIFF
            else ReviewLane.CONTENT
        )
        item.risk_level = classify_risk(item)
        item.analysis_stage = stage
        item.decision_reason = item.decision_reason or (
            "visual_change_without_reliable_text"
            if item.review_lane == ReviewLane.NEEDS_VISUAL_REVIEW
            else "reliable_content_evidence"
        )
        if not item.evidence:
            item.evidence = [
                DiffEvidence(
                    source=source,
                    kind=item.diff_type.value,
                    old_value=item.old_value,
                    new_value=item.new_value,
                    old_bbox=item.old_bbox,
                    new_bbox=item.new_bbox,
                    confidence=item.confidence,
                )
            ]
        item.model_manifest = dict(manifest)
    return items


def unresolved_region_count(items: list[DiffItem]) -> int:
    return sum(item.review_lane == ReviewLane.NEEDS_VISUAL_REVIEW for item in items)
