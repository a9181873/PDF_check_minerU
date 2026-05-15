from enum import Enum

from pydantic import BaseModel, Field


class DiffType(str, Enum):
    TEXT_MODIFIED = "text_modified"
    NUMBER_MODIFIED = "number_modified"
    ADDED = "added"
    DELETED = "deleted"
    IMAGE_DIFF = "image_diff"


class BBox(BaseModel):
    """PDF coordinate bounding box, bottom-left origin in pt."""

    page: int = Field(ge=1)
    x0: float
    y0: float
    x1: float
    y1: float


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


class DiffReport(BaseModel):
    project_id: str
    case_number: str | None = None
    old_filename: str
    new_filename: str
    created_at: str
    total_diffs: int
    items: list[DiffItem]
    summary: str | None = None


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
