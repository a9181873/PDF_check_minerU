from pydantic import BaseModel
from typing import Literal

from models.diff_models import DiffReport


class UploadResponse(BaseModel):
    task_id: str
    status: str


class CompareStatusResponse(BaseModel):
    task_id: str
    status: str
    progress_percent: int
    current_step: str
    error_message: str | None = None


class ProjectCreateRequest(BaseModel):
    name: str


class ProjectResponse(BaseModel):
    id: str
    name: str
    created_at: str
    updated_at: str


class ReviewActionRequest(BaseModel):
    diff_item_id: str
    action: Literal["confirmed", "flagged"]
    note: str | None = None


class ReviewActionResponse(BaseModel):
    ok: bool
    reviewer: str
    reviewed_at: str


class ReviewSummaryResponse(BaseModel):
    total: int
    confirmed: int
    flagged: int
    pending: int


class TaskResultResponse(BaseModel):
    report: DiffReport
