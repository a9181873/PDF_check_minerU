from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.task_store import TASK_STORE
from models.database import (
    get_archive_by_comparison,
    get_comparison,
    get_comparison_report,
    get_verification_sessions_by_archive,
)
from services.archive_service import (
    archive_comparison,
    compute_pdf_hash,
    record_verification,
)

router = APIRouter(prefix="/api/archive", tags=["archive"])


class VerifyRequest(BaseModel):
    reviewer: str | None = None
    notes: str | None = None


def _load_report(comparison_id: str):
    state = TASK_STORE.get(comparison_id)
    if state and state.result:
        return state.result
    return get_comparison_report(comparison_id)


@router.post("/{comparison_id}/verify")
async def verify_and_archive(comparison_id: str, payload: VerifyRequest):
    comp = get_comparison(comparison_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Comparison not found")
    if comp.get("status") != "done":
        raise HTTPException(status_code=400, detail="Comparison not completed yet")

    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison report not found")

    old_path = Path(comp["old_file_path"])
    new_path = Path(comp["new_file_path"])
    if not old_path.exists() or not new_path.exists():
        raise HTTPException(status_code=404, detail="Source PDF files not found")

    old_hash = comp.get("old_hash") or compute_pdf_hash(old_path)
    new_hash = comp.get("new_hash") or compute_pdf_hash(new_path)

    archive_record, is_new = archive_comparison(
        comparison_id=comparison_id,
        report=report,
        old_path=old_path,
        new_path=new_path,
        old_hash=old_hash,
        new_hash=new_hash,
    )

    session = record_verification(
        archive_id=archive_record["id"],
        comparison_id=comparison_id,
        reviewer=payload.reviewer,
        report=report,
        notes=payload.notes,
    )

    return {
        "archive_id": archive_record["id"],
        "session_id": session["id"],
        "is_new_archive": is_new,
        "verified_at": session["verified_at"],
    }


@router.get("/{comparison_id}/history")
async def get_history(comparison_id: str):
    archive = get_archive_by_comparison(comparison_id)
    if not archive:
        return {"archive": None, "sessions": []}

    sessions = get_verification_sessions_by_archive(archive["id"])
    return {"archive": archive, "sessions": sessions}


@router.get("/by-archive/{archive_id}/sessions")
async def get_sessions_by_archive(archive_id: str):
    sessions = get_verification_sessions_by_archive(archive_id)
    return {"sessions": sessions}


@router.get("/files/{archive_id}/{file_type}")
async def download_archive_file(archive_id: str, file_type: str):
    from models.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM pdf_archives WHERE id = ?", (archive_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Archive not found")

    archive = dict(row)
    path_map = {
        "old_pdf": archive.get("old_archive_path"),
        "new_pdf": archive.get("new_archive_path"),
        "annotated_pdf": archive.get("annotated_archive_path"),
    }

    if file_type not in path_map:
        raise HTTPException(status_code=400, detail="file_type must be old_pdf, new_pdf, or annotated_pdf")

    file_path = path_map[file_type]
    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File not found in archive")

    filename_map = {
        "old_pdf": f"old_{archive['old_filename']}",
        "new_pdf": f"new_{archive['new_filename']}",
        "annotated_pdf": "annotated.pdf",
    }

    return FileResponse(
        path=file_path,
        filename=filename_map[file_type],
        media_type="application/pdf",
    )
