import io
import logging
import re
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from api.routes_auth import get_current_user
from api.task_store import TASK_STORE
from config import settings
from models.database import (
    create_comparison,
    ensure_default_project,
    get_comparison,
    get_markdown_paths as db_get_markdown_paths,
    get_comparison_report,
    get_snapshot_dir,
    project_exists,
    save_comparison_error,
    save_diff_report,
    save_markdown_paths,
    save_snapshot_dir,
    update_comparison_hashes,
    update_comparison_status,
)
from models.schemas import CompareStatusResponse, UploadResponse
from services.archive_service import compute_pdf_hash
from services.diff_service import generate_diff_report
from services.parser_service import parse_pdf, save_markdown

router = APIRouter(prefix="/api/compare", tags=["compare"], dependencies=[Depends(get_current_user)])

_PDF_CACHE_HEADERS = {"Cache-Control": "private, max-age=86400"}
_logger = logging.getLogger(__name__)


def _assert_pdf(file: UploadFile) -> None:
    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")
    try:
        pos = file.file.tell()
        header = file.file.read(5)
        file.file.seek(pos)
    except OSError:
        raise HTTPException(status_code=400, detail=f"Unable to inspect uploaded file: {filename}")
    if header != b"%PDF-":
        raise HTTPException(status_code=400, detail=f"Invalid PDF file: {filename}")


def _save_upload(file: UploadFile, dest_dir: Path, task_id: str) -> Path:
    safe_name = f"{task_id}_{Path(file.filename or 'upload.pdf').name}"
    path = dest_dir / safe_name
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    total = 0
    chunk_size = 1024 * 1024  # 1MB
    try:
        with path.open("wb") as target:
            while True:
                chunk = file.file.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"檔案超過大小限制 {settings.max_upload_size_mb}MB",
                    )
                target.write(chunk)
    except HTTPException:
        path.unlink(missing_ok=True)
        raise
    return path


def _set_task_progress(task_id: str, status: str, percent: int, step: str) -> None:
    def updater(state):
        state.status = status
        state.progress_percent = percent
        state.current_step = step

    TASK_STORE.update(task_id, updater)


def _set_task_error(task_id: str, message: str) -> None:
    def updater(state):
        state.status = "error"
        state.current_step = "failed"
        state.error_message = message

    TASK_STORE.update(task_id, updater)


def _markdown_output_paths(task_id: str) -> tuple[Path, Path]:
    return (
        settings.markdown_export_dir / f"{task_id}_old.md",
        settings.markdown_export_dir / f"{task_id}_new.md",
    )


def _elapsed_since(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 3)


def _parse_pdf_with_timing(file_path: str):
    started_at = time.perf_counter()
    doc = parse_pdf(file_path)
    return doc, _elapsed_since(started_at)


def _parse_pdf_pair(task_id: str, old_path: str, new_path: str):
    started_at = time.perf_counter()
    timings: dict[str, float] = {}

    if not settings.parallel_pdf_parse:
        _set_task_progress(task_id, "parsing", 10, "解析舊版 PDF")
        old_doc, timings["parse_old_seconds"] = _parse_pdf_with_timing(old_path)
        _set_task_progress(task_id, "parsing", 45, "解析新版 PDF")
        new_doc, timings["parse_new_seconds"] = _parse_pdf_with_timing(new_path)
        timings["parse_total_seconds"] = _elapsed_since(started_at)
        return old_doc, new_doc, timings

    _set_task_progress(task_id, "parsing", 10, "並行解析新舊 PDF")
    results = {}
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"parse-{task_id[:8]}") as pool:
        futures = {
            pool.submit(_parse_pdf_with_timing, old_path): "old",
            pool.submit(_parse_pdf_with_timing, new_path): "new",
        }
        for future in as_completed(futures):
            side = futures[future]
            doc, elapsed = future.result()
            results[side] = doc
            timings[f"parse_{side}_seconds"] = elapsed
            _set_task_progress(
                task_id,
                "parsing",
                30 if len(results) == 1 else 55,
                "舊版 PDF 解析完成" if side == "old" else "新版 PDF 解析完成",
            )

    timings["parse_total_seconds"] = _elapsed_since(started_at)
    return results["old"], results["new"], timings


def _generate_review_artifacts(
    task_id: str,
    old_path: str,
    new_path: str,
    report,
) -> dict[str, float]:
    timings: dict[str, float] = {}
    started_at = time.perf_counter()

    if settings.generate_snapshots:
        snap_started = time.perf_counter()
        try:
            from services.snapshot_service import generate_comparison_snapshots

            settings.snapshots_dir.mkdir(parents=True, exist_ok=True)
            snap_dir = generate_comparison_snapshots(
                task_id=task_id,
                old_pdf_path=old_path,
                new_pdf_path=new_path,
                report=report,
                snapshot_base_dir=settings.snapshots_dir,
                diff_pages_only=settings.snapshot_diff_pages_only,
            )
            save_snapshot_dir(task_id, str(snap_dir))
        except Exception as exc:
            _logger.warning("Snapshot generation failed for task %s: %s", task_id, exc)
        finally:
            timings["snapshot_seconds"] = _elapsed_since(snap_started)

    crop_started = time.perf_counter()
    try:
        from services.snapshot_service import generate_diff_crops

        settings.crops_dir.mkdir(parents=True, exist_ok=True)
        generate_diff_crops(
            task_id=task_id,
            old_pdf_path=old_path,
            new_pdf_path=new_path,
            report=report,
            crops_base_dir=settings.crops_dir,
        )
    except Exception as exc:
        _logger.warning("Crop generation failed for task %s: %s", task_id, exc)
    finally:
        timings["crop_seconds"] = _elapsed_since(crop_started)
        timings["artifact_total_seconds"] = _elapsed_since(started_at)
        _logger.info("Generated review artifacts for task %s: %s", task_id, timings)
    return timings


def _start_review_artifact_generation(
    task_id: str,
    old_path: str,
    new_path: str,
    report,
) -> None:
    worker = threading.Thread(
        target=_generate_review_artifacts,
        args=(task_id, old_path, new_path, report),
        name=f"artifacts-{task_id[:8]}",
        daemon=True,
    )
    worker.start()


def _find_uploaded_pdf(task_id: str, row, version: str) -> Path | None:
    upload_dir = settings.old_upload_dir if version == "old" else settings.new_upload_dir
    original_filename = row["old_filename"] if version == "old" else row["new_filename"]
    stored_path = Path(row["old_file_path"] if version == "old" else row["new_file_path"])

    expected_name = f"{task_id}_{Path(original_filename).name}"
    expected_path = upload_dir / expected_name
    if expected_path.exists():
        return expected_path

    candidates = sorted(upload_dir.glob(f"{task_id}_*.pdf"))
    if candidates:
        return candidates[0]
    return stored_path if stored_path.exists() else None


def _run_compare_task(
    task_id: str,
    project_id: str,
    case_number: str | None,
    old_path: str,
    new_path: str,
    old_name: str,
    new_name: str,
) -> None:
    # Start resource monitoring
    from services.resource_monitor import ResourceMonitor, save_resource_log
    monitor = ResourceMonitor(task_id)
    monitor.start()
    task_started_at = time.perf_counter()
    timings: dict[str, float] = {}

    try:
        update_comparison_status(task_id, "parsing")
        old_doc, new_doc, parse_timings = _parse_pdf_pair(task_id, old_path, new_path)
        timings.update(parse_timings)
        old_doc_engine = old_doc.raw_json.get("engine", "unknown")

        markdown_started_at = time.perf_counter()
        old_md_path, new_md_path = _markdown_output_paths(task_id)
        save_markdown(old_doc, old_md_path, source_name=old_name)
        save_markdown(new_doc, new_md_path, source_name=new_name)
        save_markdown_paths(
            task_id,
            old_markdown_path=str(old_md_path),
            new_markdown_path=str(new_md_path),
        )
        timings["markdown_seconds"] = _elapsed_since(markdown_started_at)

        update_comparison_status(task_id, "diffing")
        _set_task_progress(task_id, "diffing", 80, "running diff engine")
        diff_started_at = time.perf_counter()
        report = generate_diff_report(
            project_id=project_id,
            old_filename=old_name,
            new_filename=new_name,
            old_doc=old_doc,
            new_doc=new_doc,
            old_pdf_path=old_path,
            new_pdf_path=new_path,
        )
        timings["diff_seconds"] = _elapsed_since(diff_started_at)
        report.case_number = case_number.strip() if case_number else None
        if not report.summary:
            report.summary = f"parser_old={old_doc_engine}, parser_new={new_doc.raw_json.get('engine', 'unknown')}"
        report.engine_stats["pipeline_timings_seconds"] = {
            **report.engine_stats.get("pipeline_timings_seconds", {}),
            **timings,
            "report_ready_seconds": _elapsed_since(task_started_at),
        }
        report.engine_stats["pipeline_options"] = {
            **report.engine_stats.get("pipeline_options", {}),
            "parallel_pdf_parse": bool(settings.parallel_pdf_parse),
            "postprocess_artifacts_after_done": bool(settings.postprocess_artifacts_after_done),
        }

        if not settings.postprocess_artifacts_after_done:
            _set_task_progress(task_id, "snapshotting", 90, "產生截圖與裁切")
            report.engine_stats["artifact_timings_seconds"] = _generate_review_artifacts(
                task_id,
                old_path,
                new_path,
                report,
            )

        save_diff_report(task_id, report)
        del old_doc, new_doc

        def updater(state):
            state.status = "done"
            state.progress_percent = 100
            state.current_step = "complete"
            state.result = None
            state.error_message = None

        TASK_STORE.update(task_id, updater)

        # Stop monitor and save resource log
        res_log = monitor.stop(old_filename=old_name, new_filename=new_name, total_diffs=report.total_diffs)
        try:
            save_resource_log(res_log)
        except Exception:
            pass

        if settings.postprocess_artifacts_after_done:
            try:
                _start_review_artifact_generation(task_id, old_path, new_path, report)
            except Exception as exc:
                _logger.warning("Failed to start review artifact generation for task %s: %s", task_id, exc)

    except Exception as exc:  # pragma: no cover - defensive wrapper
        monitor.stop(old_filename=old_name, new_filename=new_name)
        message = str(exc)
        save_comparison_error(task_id, message)
        _set_task_error(task_id, message)


@router.post("/upload", response_model=UploadResponse)
async def upload_compare_files(
    background_tasks: BackgroundTasks,
    case_number: str | None = Form(None),
    project_id: str | None = Form(None),
    old_pdf: UploadFile = File(...),
    new_pdf: UploadFile = File(...),
):
    _assert_pdf(old_pdf)
    _assert_pdf(new_pdf)

    if project_id:
        stripped_id = project_id.strip()
        if project_exists(stripped_id):
            resolved_project_id = stripped_id
        else:
            from models.database import create_project
            new_proj = create_project(stripped_id)
            resolved_project_id = new_proj["id"]
    else:
        resolved_project_id = ensure_default_project()

    task_id = str(uuid.uuid4())
    TASK_STORE.create(task_id)

    old_path = _save_upload(old_pdf, settings.old_upload_dir, task_id)
    new_path = _save_upload(new_pdf, settings.new_upload_dir, task_id)

    create_comparison(
        comparison_id=task_id,
        project_id=resolved_project_id,
        old_filename=old_pdf.filename or old_path.name,
        new_filename=new_pdf.filename or new_path.name,
        old_file_path=str(old_path),
        new_file_path=str(new_path),
        case_number=case_number,
    )

    try:
        old_hash = compute_pdf_hash(old_path)
        new_hash = compute_pdf_hash(new_path)
        update_comparison_hashes(task_id, old_hash, new_hash)
    except Exception:
        pass

    background_tasks.add_task(
        _run_compare_task,
        task_id,
        resolved_project_id,
        case_number,
        str(old_path),
        str(new_path),
        old_pdf.filename or old_path.name,
        new_pdf.filename or new_path.name,
    )

    return UploadResponse(task_id=task_id, status="parsing")


@router.post("/recompare/{task_id}", response_model=UploadResponse)
async def recompare(task_id: str, background_tasks: BackgroundTasks):
    """Re-run the diff engine on an existing comparison without re-uploading files."""
    comp = get_comparison(task_id)
    if not comp:
        raise HTTPException(status_code=404, detail="Comparison not found")

    old_path = comp.get("old_file_path", "")
    new_path = comp.get("new_file_path", "")
    if not old_path or not new_path:
        raise HTTPException(status_code=400, detail="Original PDF files not found")

    # Reset task state
    TASK_STORE.create(task_id)
    update_comparison_status(task_id, "parsing")

    background_tasks.add_task(
        _run_compare_task,
        task_id,
        comp.get("project_id", ""),
        comp.get("case_number"),
        old_path,
        new_path,
        comp.get("old_filename", "old.pdf"),
        comp.get("new_filename", "new.pdf"),
    )

    return UploadResponse(task_id=task_id, status="parsing")


@router.get("/{task_id}/status", response_model=CompareStatusResponse)
async def get_compare_status(task_id: str):
    state = TASK_STORE.get(task_id)
    if state:
        return CompareStatusResponse(
            task_id=task_id,
            status=state.status,
            progress_percent=state.progress_percent,
            current_step=state.current_step,
            error_message=state.error_message,
        )

    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    status = row.get("status", "pending")
    percent = 100 if status == "done" else 0
    current_step = "complete" if status == "done" else status

    return CompareStatusResponse(
        task_id=task_id,
        status=status,
        progress_percent=percent,
        current_step=current_step,
        error_message=row.get("error_message"),
    )


@router.get("/{task_id}/result")
async def get_compare_result(task_id: str):
    state = TASK_STORE.get(task_id)
    if state and state.status == "done" and state.result:
        return state.result

    report = get_comparison_report(task_id)
    if report:
        return report

    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    raise HTTPException(status_code=409, detail="Task not completed")


@router.get("/{task_id}/markdown")
async def get_markdown_manifest(task_id: str):
    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    markdown_paths = db_get_markdown_paths(task_id)
    if not markdown_paths:
        raise HTTPException(status_code=404, detail="Task not found")

    old_path = markdown_paths.get("old_markdown_path")
    new_path = markdown_paths.get("new_markdown_path")
    return {
        "task_id": task_id,
        "old_markdown_path": old_path,
        "new_markdown_path": new_path,
        "old_download_url": f"/api/compare/{task_id}/markdown/old" if old_path else None,
        "new_download_url": f"/api/compare/{task_id}/markdown/new" if new_path else None,
    }


@router.get("/{task_id}/markdown/{version}")
async def download_markdown(task_id: str, version: str):
    normalized = version.strip().lower()
    if normalized not in {"old", "new"}:
        raise HTTPException(status_code=400, detail="version must be 'old' or 'new'")

    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    markdown_paths = db_get_markdown_paths(task_id)
    if not markdown_paths:
        raise HTTPException(status_code=404, detail="Markdown not found")

    path_text = (
        markdown_paths.get("old_markdown_path")
        if normalized == "old"
        else markdown_paths.get("new_markdown_path")
    )
    if not path_text:
        raise HTTPException(status_code=404, detail="Markdown not found")

    path_obj = Path(path_text)
    if not path_obj.exists():
        raise HTTPException(status_code=404, detail="Markdown file missing")

    source_name = row["old_filename"] if normalized == "old" else row["new_filename"]
    download_name = f"{Path(source_name).stem}_{normalized}.md"
    return FileResponse(path_obj, media_type="text/markdown; charset=utf-8", filename=download_name)


@router.get("/{task_id}/snapshots")
async def list_snapshots(task_id: str):
    """List available snapshot files for a comparison."""
    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    snap_dir_str = get_snapshot_dir(task_id)
    if not snap_dir_str:
        raise HTTPException(status_code=404, detail="Snapshots not yet generated")

    snap_dir = Path(snap_dir_str)
    if not snap_dir.exists():
        raise HTTPException(status_code=404, detail="Snapshot directory missing")

    files = sorted(snap_dir.iterdir(), key=lambda p: p.name)
    return {
        "task_id": task_id,
        "snapshot_dir": str(snap_dir),
        "files": [
            {
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "download_url": f"/api/compare/{task_id}/snapshots/{f.name}",
            }
            for f in files
            if f.is_file()
        ],
        "download_zip_url": f"/api/compare/{task_id}/snapshots/download.zip",
    }


@router.get("/{task_id}/snapshots/download.zip")
async def download_snapshots_zip(task_id: str):
    """Download all snapshot files as a ZIP archive."""
    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    snap_dir_str = get_snapshot_dir(task_id)
    if not snap_dir_str:
        raise HTTPException(status_code=404, detail="Snapshots not yet generated")

    snap_dir = Path(snap_dir_str)
    if not snap_dir.exists():
        raise HTTPException(status_code=404, detail="Snapshot directory missing")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(snap_dir.iterdir()):
            if f.is_file():
                zf.write(f, arcname=f.name)
    buf.seek(0)

    zip_name = f"snapshot_{task_id[:8]}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )


@router.get("/{task_id}/snapshots/{filename}")
async def download_snapshot_file(task_id: str, filename: str):
    """Download a single snapshot file (PNG or JSON)."""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    snap_dir_str = get_snapshot_dir(task_id)
    if not snap_dir_str:
        raise HTTPException(status_code=404, detail="Snapshots not yet generated")

    file_path = Path(snap_dir_str) / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Snapshot file not found")

    media_type = "image/png" if filename.endswith(".png") else "application/json"
    return FileResponse(file_path, media_type=media_type, filename=filename)


@router.get("/{task_id}/pdf/{version}")
async def download_pdf(task_id: str, version: str):
    normalized = version.strip().lower()
    if normalized not in {"old", "new"}:
        raise HTTPException(status_code=400, detail="version must be 'old' or 'new'")

    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    original_filename = row["old_filename"] if normalized == "old" else row["new_filename"]
    pdf_path = _find_uploaded_pdf(task_id, row, normalized)
    if pdf_path:
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=original_filename,
            headers=_PDF_CACHE_HEADERS,
        )

    raise HTTPException(status_code=404, detail="PDF file not found")


_DIFF_ID_RE = re.compile(r"^d\d{3,}$")


@router.get("/{task_id}/crop/{diff_id}/{side}")
async def get_diff_crop(task_id: str, diff_id: str, side: str):
    """Return a cropped PNG of a diff region from the old/new PDF.

    Generated post-compare by snapshot_service.generate_diff_crops.
    """
    if not _DIFF_ID_RE.match(diff_id):
        raise HTTPException(status_code=400, detail="Invalid diff id")

    normalized = side.strip().lower()
    if normalized not in {"old", "new"}:
        raise HTTPException(status_code=400, detail="side must be 'old' or 'new'")

    row = get_comparison(task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")

    crop_path = settings.crops_dir / task_id / f"{diff_id}_{normalized}.png"
    if not crop_path.exists():
        report = get_comparison_report(task_id)
        if not report:
            raise HTTPException(status_code=404, detail="Comparison report not found")

        target = next((item for item in report.items if item.id == diff_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Diff item not found")

        bbox = target.old_bbox if normalized == "old" else target.new_bbox
        if not bbox:
            raise HTTPException(status_code=404, detail="Crop not available for this side")

        old_pdf_path = _find_uploaded_pdf(task_id, row, "old")
        new_pdf_path = _find_uploaded_pdf(task_id, row, "new")
        if not old_pdf_path or not new_pdf_path:
            raise HTTPException(status_code=404, detail="Source PDF not found")

        try:
            from services.snapshot_service import generate_diff_crops

            settings.crops_dir.mkdir(parents=True, exist_ok=True)
            generate_diff_crops(
                task_id=task_id,
                old_pdf_path=str(old_pdf_path),
                new_pdf_path=str(new_pdf_path),
                report=report,
                crops_base_dir=settings.crops_dir,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Crop generation failed") from exc

        if not crop_path.exists():
            raise HTTPException(status_code=404, detail="Crop not found")

    return FileResponse(crop_path, media_type="image/png")
