from collections import OrderedDict
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from api.routes_auth import get_current_user
from api.task_store import TASK_STORE
from config import settings
from models.database import get_checklist, get_comparison_report, save_checklist
from models.diff_models import CheckStatus, ChecklistItem
from services.checklist_service import auto_match, import_checklist

router = APIRouter(prefix="/api/checklist", tags=["checklist"], dependencies=[Depends(get_current_user)])

# Bounded LRU cache — falls back to DB on miss. Capped to prevent memory growth.
_CACHE_MAX = 50
CHECKLIST_STORE: "OrderedDict[str, list[ChecklistItem]]" = OrderedDict()


def _cache_set(comparison_id: str, items: list[ChecklistItem]) -> None:
    CHECKLIST_STORE[comparison_id] = items
    CHECKLIST_STORE.move_to_end(comparison_id)
    while len(CHECKLIST_STORE) > _CACHE_MAX:
        CHECKLIST_STORE.popitem(last=False)


def _cache_get(comparison_id: str) -> list[ChecklistItem] | None:
    items = CHECKLIST_STORE.get(comparison_id)
    if items is not None:
        CHECKLIST_STORE.move_to_end(comparison_id)
    return items


def _load_report(comparison_id: str):
    state = TASK_STORE.get(comparison_id)
    if state and state.result:
        return state.result
    return get_comparison_report(comparison_id)


@router.post("/{comparison_id}/import")
async def import_checklist_api(comparison_id: str, checklist_csv: UploadFile = File(...)):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    suffix = Path(checklist_csv.filename or "checklist.csv").suffix or ".csv"
    temp_file = settings.uploads_dir / f"{comparison_id}_checklist{suffix}"
    try:
        with temp_file.open("wb") as fh:
            fh.write(await checklist_csv.read())
        checklist = import_checklist(str(temp_file))
    finally:
        try:
            temp_file.unlink(missing_ok=True)
        except OSError:
            pass

    matched = auto_match(checklist, report.items)
    _cache_set(comparison_id, matched)
    save_checklist(comparison_id, matched)

    auto_matched_count = sum(1 for item in matched if item.matched_diff_id)
    return {"items_count": len(matched), "auto_matched_count": auto_matched_count}


@router.get("/{comparison_id}")
async def list_checklist_api(comparison_id: str):
    cached = _cache_get(comparison_id)
    if cached is not None:
        return cached

    items = get_checklist(comparison_id)
    if items:
        _cache_set(comparison_id, items)
    return items


@router.patch("/{comparison_id}/{item_id}")
async def patch_checklist_item(comparison_id: str, item_id: str, payload: dict):
    items = _cache_get(comparison_id)
    if not items:
        items = get_checklist(comparison_id)
        if items:
            _cache_set(comparison_id, items)
    if not items:
        raise HTTPException(status_code=404, detail="Checklist not found")

    target = next((item for item in items if item.item_id == item_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    if "status" in payload:
        try:
            target.status = CheckStatus(payload["status"])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid status value") from exc
    if "note" in payload:
        target.note = payload["note"]

    save_checklist(comparison_id, items)
    return {"ok": True}
