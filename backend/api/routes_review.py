from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from api.routes_auth import get_current_user, user_display_label
from api.task_store import TASK_STORE
from models.database import (
    add_review_log,
    get_comparison_report,
    get_review_counts,
    save_comparison_report_state,
    update_review_item_state,
)
from models.schemas import ReviewActionRequest, ReviewActionResponse, ReviewSummaryResponse

router = APIRouter(prefix="/api/review", tags=["review"], dependencies=[Depends(get_current_user)])


def _load_report(comparison_id: str):
    state = TASK_STORE.get(comparison_id)
    if state and state.result:
        return state.result
    return get_comparison_report(comparison_id)


@router.post("/{comparison_id}/confirm", response_model=ReviewActionResponse)
async def confirm_diff(
    comparison_id: str,
    payload: ReviewActionRequest,
    current_user: dict = Depends(get_current_user),
):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    target = next((d for d in report.items if d.id == payload.diff_item_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Diff item not found")

    reviewer = user_display_label(current_user)
    target.reviewed = True
    target.reviewed_by = reviewer
    target.reviewed_at = datetime.now(timezone.utc).isoformat()
    target.flagged = payload.action == "flagged"

    add_review_log(
        comparison_id=comparison_id,
        diff_item_id=payload.diff_item_id,
        action=payload.action,
        reviewer=reviewer,
        note=payload.note,
    )
    # Persist just this item atomically — overwriting the whole report blob would
    # drop a concurrent reviewer's edit to a different item.
    persisted = update_review_item_state(
        comparison_id,
        payload.diff_item_id,
        reviewed=target.reviewed,
        reviewed_by=target.reviewed_by,
        reviewed_at=target.reviewed_at,
        flagged=target.flagged,
    )
    if not persisted:
        # The durable report blob had no row/item to patch (e.g. result served from
        # the in-memory task store but not yet written to SQLite). Fall back to
        # writing the full report so this review state is not silently lost. The
        # review_logs row above is already the source of truth for the counts.
        save_comparison_report_state(comparison_id, report)

    return {"ok": True, "reviewer": reviewer, "reviewed_at": target.reviewed_at}


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
