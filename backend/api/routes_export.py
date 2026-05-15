import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from fastapi.responses import FileResponse

from api.routes_auth import get_current_user
from api.task_store import TASK_STORE
from config import settings
from models.database import get_checklist, get_comparison_report, get_review_counts, get_review_logs
from services.export_service import (
    export_annotated_pdf,
    export_review_excel,
    export_review_log_csv,
    export_review_log_json,
    export_review_log_txt,
    export_review_report_pdf,
)

router = APIRouter(prefix="/api/export", tags=["export"], dependencies=[Depends(get_current_user)])


def _resolve_new_pdf_path(task_id: str, filename: str) -> Path | None:
    direct = settings.new_upload_dir / f"{task_id}_{Path(filename).name}"
    if direct.exists():
        return direct

    candidates = list(settings.new_upload_dir.glob(f"{task_id}_*.pdf"))
    return candidates[0] if candidates else None


def _load_report(comparison_id: str):
    state = TASK_STORE.get(comparison_id)
    if state and state.result:
        return state.result
    return get_comparison_report(comparison_id)


def _report_date_tag(created_at: str) -> str:
    return created_at.split("T", 1)[0].replace("-", "")


def _generate_filename(prefix: str, report, extension: str) -> str:
    import os
    import re
    from datetime import datetime
    
    old_base = Path(report.old_filename).stem if getattr(report, "old_filename", None) else ""
    new_base = Path(report.new_filename).stem if getattr(report, "new_filename", None) else ""
    
    common = os.path.commonprefix([old_base, new_base]).strip(" _-")
    if not common:
        common = report.project_id if getattr(report, "project_id", None) else "Unnamed"

    case_number = getattr(report, "case_number", None)
    if case_number:
        safe_case = re.sub(r"[^\w.-]+", "_", str(case_number).strip(), flags=re.UNICODE).strip("._-")
        if safe_case:
            common = f"{safe_case}_{common}"
        
    audit_date = datetime.now().strftime("%Y%m%d")
    return f"{common}_{prefix}_{audit_date}.{extension}"


@router.get("/{comparison_id}/pdf")
async def export_pdf(comparison_id: str):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    source_pdf = _resolve_new_pdf_path(comparison_id, report.new_filename)
    if not source_pdf:
        raise HTTPException(status_code=404, detail="Source PDF not found")

    filename = _generate_filename("差異標註版", report, "pdf")
    output = settings.export_dir / filename
    try:
        exported = export_annotated_pdf(str(source_pdf), report.items, str(output))
    except RuntimeError as exc:
        logger.exception("annotated PDF export failed for %s", comparison_id)
        raise HTTPException(status_code=503, detail="匯出標註 PDF 失敗，請稍後再試") from exc
    return FileResponse(
        exported,
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/{comparison_id}/excel")
async def export_excel(comparison_id: str):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    checklist = get_checklist(comparison_id)
    review_counts = get_review_counts(comparison_id)
    filename = _generate_filename("差異檢核明細", report, "xlsx")
    output = settings.export_dir / filename
    exported = export_review_excel(
        comparison_id,
        report,
        checklist=checklist,
        review_counts=review_counts,
        output_path=str(output),
    )
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(
        exported,
        media_type=media,
        filename=filename,
    )


@router.get("/{comparison_id}/report")
async def export_report(comparison_id: str):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    checklist = get_checklist(comparison_id)
    review_counts = get_review_counts(comparison_id)
    filename = _generate_filename("差異檢核報告", report, "pdf")
    output = settings.export_dir / filename
    try:
        exported = export_review_report_pdf(
            comparison_id,
            report,
            checklist=checklist,
            review_counts=review_counts,
            output_path=str(output),
        )
    except RuntimeError as exc:
        logger.exception("review report PDF export failed for %s", comparison_id)
        raise HTTPException(status_code=503, detail="匯出差異檢核報告失敗，請稍後再試") from exc
    return FileResponse(
        exported,
        media_type="application/pdf",
        filename=filename,
    )


@router.get("/{comparison_id}/log")
async def export_log(comparison_id: str):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    checklist = get_checklist(comparison_id)
    review_counts = get_review_counts(comparison_id)
    review_logs = get_review_logs(comparison_id)
    filename = _generate_filename("完整審核Log", report, "json")
    output = settings.export_dir / filename
    exported = export_review_log_json(
        comparison_id,
        report,
        checklist=checklist,
        review_counts=review_counts,
        review_logs=review_logs,
        output_path=str(output),
    )
    return FileResponse(
        exported,
        media_type="application/json",
        filename=filename,
    )


@router.get("/{comparison_id}/log-txt")
async def export_log_txt(comparison_id: str):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    checklist = get_checklist(comparison_id)
    review_counts = get_review_counts(comparison_id)
    review_logs = get_review_logs(comparison_id)
    filename = _generate_filename("審核紀錄", report, "txt")
    output = settings.export_dir / filename
    exported = export_review_log_txt(
        comparison_id,
        report,
        checklist=checklist,
        review_counts=review_counts,
        review_logs=review_logs,
        output_path=str(output),
    )
    return FileResponse(
        exported,
        media_type="text/plain; charset=utf-8",
        filename=filename,
    )


@router.get("/{comparison_id}/log-csv")
async def export_log_csv(comparison_id: str):
    report = _load_report(comparison_id)
    if not report:
        raise HTTPException(status_code=404, detail="Comparison not found")

    checklist = get_checklist(comparison_id)
    review_logs = get_review_logs(comparison_id)
    filename = _generate_filename("審核Log", report, "csv")
    output = settings.export_dir / filename
    exported = export_review_log_csv(
        comparison_id,
        report,
        checklist=checklist,
        review_logs=review_logs,
        output_path=str(output),
    )
    return FileResponse(
        exported,
        media_type="text/csv; charset=utf-8",
        filename=filename,
    )
