from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DiffType(str, Enum):
    TEXT_MODIFIED = "text_modified"
    NUMBER_MODIFIED = "number_modified"
    ADDED = "added"
    DELETED = "deleted"
    IMAGE_DIFF = "image_diff"


class ReviewLane(str, Enum):
    """Reviewer-facing lane; visual uncertainty must never be silently hidden."""

    CONTENT = "content"
    NEEDS_VISUAL_REVIEW = "needs_visual_review"


class RiskLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AnalysisStage(str, Enum):
    PRELIMINARY = "preliminary"
    ENRICHED = "enriched"
    FINAL = "final"


class AnalysisStatus(str, Enum):
    PRELIMINARY = "preliminary"
    ENRICHING = "enriching"
    COMPLETE = "complete"


class BBox(BaseModel):
    """PDF coordinate bounding box, bottom-left origin in pt."""

    page: int = Field(ge=1)
    x0: float
    y0: float
    x1: float
    y1: float


class CandidateRegion(BaseModel):
    """Canonical page region shared by visual, OCR, table, and VLM evidence."""

    candidate_id: str
    page: int = Field(ge=1)
    region_type: str
    old_bbox: BBox | None = None
    new_bbox: BBox | None = None
    area_pt2: float = Field(default=0.0, ge=0.0)


class DiffEvidence(BaseModel):
    source: str
    kind: str
    old_value: str | None = None
    new_value: str | None = None
    old_bbox: BBox | None = None
    new_bbox: BBox | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TableCellArtifact(BaseModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    text: str
    bbox: BBox | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class TableArtifact(BaseModel):
    page: int = Field(ge=1)
    bbox: BBox
    rows: int = Field(ge=0)
    columns: int = Field(ge=0)
    cells: list[TableCellArtifact] = Field(default_factory=list)
    source: str
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    structure_signature: str


class DiffItem(BaseModel):
    id: str
    diff_type: DiffType
    old_value: str | None = None
    new_value: str | None = None
    old_bbox: BBox | None = None
    new_bbox: BBox | None = None
    old_image_base64: str | None = None
    new_image_base64: str | None = None
    context: str
    confidence: float = Field(ge=0.0, le=1.0)
    reviewed: bool = False
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    flagged: bool = False  # reviewer marked this diff as an anomaly (action == "flagged")
    candidate_id: str | None = None
    candidate_region: CandidateRegion | None = None
    review_lane: ReviewLane = ReviewLane.CONTENT
    risk_level: RiskLevel = RiskLevel.MEDIUM
    analysis_stage: AnalysisStage = AnalysisStage.FINAL
    decision_reason: str | None = None
    evidence: list[DiffEvidence] = Field(default_factory=list)
    model_manifest: dict[str, str] = Field(default_factory=dict)


class DiffReport(BaseModel):
    project_id: str
    case_number: str | None = None
    old_filename: str
    new_filename: str
    created_at: str
    total_diffs: int
    items: list[DiffItem]
    summary: str | None = None
    # Count of visual-only (IMAGE_DIFF) regions detected but dropped from the
    # content list, so the UI can warn the reviewer to also check the snapshots.
    suppressed_count: int = 0
    engine_stats: dict[str, Any] = Field(default_factory=dict)
    engine_warnings: list[str] = Field(default_factory=list)
    analysis_status: AnalysisStatus = AnalysisStatus.COMPLETE
    unresolved_region_count: int = Field(default=0, ge=0)
    report_revision: int = Field(default=1, ge=1)


class CheckStatus(str, Enum):
    CONFIRMED = "confirmed"
    ANOMALY = "anomaly"
    MISSING = "missing"
    PENDING = "pending"


class ChecklistItem(BaseModel):
    item_id: str
    check_type: str
    search_keyword: str
    expected_old: str | None = None
    expected_new: str | None = None
    page_hint: int | None = None
    status: CheckStatus = CheckStatus.PENDING
    matched_diff_id: str | None = None
    note: str | None = None
