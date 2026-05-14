from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.routes_auth import get_current_user
from api.task_store import TASK_STORE
from models.database import (
    add_review_log,
    get_comparison_report,
    get_review_counts,
    save_comparison_report_state,
)
from models.schemas import ReviewActionRequest, ReviewSummaryResponse

router = APIRouter(prefix="/api/review", tags=["review"], dependencies=[Depends(get_current_user)])


def _load_report(comparison_id: str):
    state = TASK_STORE.get(comparison_id)
    if state and state.result:
        return state.result
    return get_comparison_report(comparison_id)


@router.post("/{comparison_id}/confirm")
async def confirm_diff(comparison_id: str, payload: ReviewActionRequest):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    target = next((d for d in report.items if d.id == payload.diff_item_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Diff item not found")

    target.reviewed = payload.action in {"confirmed", "flagged"}
    target.reviewed_by = payload.reviewer
    target.reviewed_at = datetime.now(timezone.utc).isoformat()

    add_review_log(
        comparison_id=comparison_id,
        diff_item_id=payload.diff_item_id,
        action=payload.action,
        reviewer=payload.reviewer,
        note=payload.note,
    )
    save_comparison_report_state(comparison_id, report)

    return {"ok": True}


@router.get("/{comparison_id}/summary", response_model=ReviewSummaryResponse)
async def review_summary(comparison_id: str):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    total = len(report.items)
    counts = get_review_counts(comparison_id)
    confirmed = counts["confirmed"]
    flagged = counts["flagged"]
    pending = max(total - confirmed - flagged, 0)

    return ReviewSummaryResponse(
        total=total,
        confirmed=confirmed,
        flagged=flagged,
        pending=pending,
    )
