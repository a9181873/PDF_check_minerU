"""Coordinate the PDF comparison pipeline outside the HTTP routing layer."""

import logging
import time

from api.task_store import TASK_STORE
from config import settings
from models.database import (
    save_comparison_error,
    save_analysis_report_state,
    save_markdown_paths,
    save_snapshot_dir,
    update_comparison_status,
)
from services.diff_service import generate_diff_report
from services.parser_service import parse_pdf, save_markdown

_logger = logging.getLogger(__name__)


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


def fail_compare_task(task_id: str, message: str) -> None:
    save_comparison_error(task_id, message)
    _set_task_error(task_id, message)


def _markdown_output_paths(task_id: str):
    return (
        settings.markdown_export_dir / f"{task_id}_old.md",
        settings.markdown_export_dir / f"{task_id}_new.md",
    )


def _elapsed_since(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 3)


def _parse_pdf_with_timing(file_path: str):
    started_at = time.perf_counter()
    document = parse_pdf(file_path)
    return document, _elapsed_since(started_at)


def parse_pdf_pair(task_id: str, old_path: str, new_path: str):
    started_at = time.perf_counter()
    timings: dict[str, float] = {}

    # PyMuPDF explicitly does not support multithreading. Keep both parses on
    # the task thread; a future parallel implementation must use isolated
    # processes and include their startup/memory cost in the benchmark.
    _set_task_progress(task_id, "parsing", 10, "解析舊版 PDF")
    old_doc, timings["parse_old_seconds"] = _parse_pdf_with_timing(old_path)
    _set_task_progress(task_id, "parsing", 45, "解析新版 PDF")
    new_doc, timings["parse_new_seconds"] = _parse_pdf_with_timing(new_path)
    timings["parse_total_seconds"] = _elapsed_since(started_at)
    return old_doc, new_doc, timings


def _generate_review_artifacts(task_id: str, old_path: str, new_path: str, report) -> dict[str, float]:
    timings: dict[str, float] = {}
    started_at = time.perf_counter()

    if settings.generate_snapshots:
        snapshot_started = time.perf_counter()
        try:
            from services.snapshot_service import generate_comparison_snapshots

            settings.snapshots_dir.mkdir(parents=True, exist_ok=True)
            snapshot_dir = generate_comparison_snapshots(
                task_id=task_id,
                old_pdf_path=old_path,
                new_pdf_path=new_path,
                report=report,
                snapshot_base_dir=settings.snapshots_dir,
                diff_pages_only=settings.snapshot_diff_pages_only,
            )
            save_snapshot_dir(task_id, str(snapshot_dir))
        except Exception as exc:
            _logger.warning("Snapshot generation failed for task %s: %s", task_id, exc)
        finally:
            timings["snapshot_seconds"] = _elapsed_since(snapshot_started)

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


def _start_review_artifact_generation(task_id: str, old_path: str, new_path: str, report) -> None:
    """Generate artifacts on the compare worker to keep PyMuPDF single-threaded.

    The task may already be marked ``done`` when the compatibility setting is
    enabled, but this function intentionally remains synchronous. A future
    asynchronous implementation must use an isolated process/worker.
    """
    _generate_review_artifacts(task_id, old_path, new_path, report)


def run_compare_task(
    task_id: str,
    project_id: str,
    case_number: str | None,
    old_path: str,
    new_path: str,
    old_name: str,
    new_name: str,
) -> None:
    from services.resource_monitor import ResourceMonitor, save_resource_log

    monitor = ResourceMonitor(task_id)
    monitor.start()
    task_started_at = time.perf_counter()
    timings: dict[str, float] = {}

    try:
        update_comparison_status(task_id, "parsing")
        old_doc, new_doc, parse_timings = parse_pdf_pair(task_id, old_path, new_path)
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
        preliminary_report = generate_diff_report(
            project_id=project_id,
            old_filename=old_name,
            new_filename=new_name,
            old_doc=old_doc,
            new_doc=new_doc,
            old_pdf_path=old_path,
            new_pdf_path=new_path,
            include_enrichment=False,
        )
        timings["preliminary_diff_seconds"] = _elapsed_since(diff_started_at)
        timings["preliminary_ready_seconds"] = _elapsed_since(task_started_at)
        preliminary_report.case_number = case_number.strip() if case_number else None
        preliminary_report.engine_stats["pipeline_timings_seconds"] = {
            **preliminary_report.engine_stats.get("pipeline_timings_seconds", {}),
            **timings,
        }
        preliminary_report = save_analysis_report_state(
            task_id, preliminary_report, complete=False
        )

        def publish_preliminary(state):
            state.status = "enriching"
            state.progress_percent = 85
            state.current_step = "OCR／表格證據補強"
            state.result = preliminary_report
            state.result_revision += 1

        TASK_STORE.update(task_id, publish_preliminary)

        needs_enrichment = bool(old_doc.is_image_pdf or new_doc.is_image_pdf)
        if needs_enrichment:
            enrichment_started_at = time.perf_counter()
            report = generate_diff_report(
                project_id=project_id,
                old_filename=old_name,
                new_filename=new_name,
                old_doc=old_doc,
                new_doc=new_doc,
                old_pdf_path=old_path,
                new_pdf_path=new_path,
                include_enrichment=True,
            )
            timings["enrichment_seconds"] = _elapsed_since(enrichment_started_at)
        else:
            from models.diff_models import AnalysisStage, AnalysisStatus

            report = preliminary_report.model_copy(deep=True)
            report.analysis_status = AnalysisStatus.COMPLETE
            for item in report.items:
                item.analysis_stage = AnalysisStage.FINAL

        timings["diff_seconds"] = _elapsed_since(diff_started_at)
        report.case_number = case_number.strip() if case_number else None
        if not report.summary:
            report.summary = f"parser_old={old_doc_engine}, parser_new={new_doc.raw_json.get('engine', 'unknown')}"
        report.engine_stats["pipeline_timings_seconds"] = {
            **report.engine_stats.get("pipeline_timings_seconds", {}),
            **timings,
            "report_ready_seconds": _elapsed_since(task_started_at),
        }
        report.engine_stats["parser_routing"] = {
            "old": old_doc.raw_json.get("routing", {}),
            "new": new_doc.raw_json.get("routing", {}),
        }
        report.engine_stats["pipeline_options"] = {
            **report.engine_stats.get("pipeline_options", {}),
            "pdf_parse_strategy": "sequential_pymupdf_safe",
            "postprocess_artifacts_after_done": bool(settings.postprocess_artifacts_after_done),
            "table_parser_strategy": settings.table_parser_strategy,
            "heavy_parser_max_concurrency": int(settings.heavy_parser_max_concurrency),
            "parser_cache_enabled": bool(settings.enable_parser_cache),
            "pixel_diff_cache_enabled": bool(settings.enable_pixel_diff_cache),
            "parallel_ocr_pairs": bool(settings.enable_parallel_ocr_pairs),
        }

        if not settings.postprocess_artifacts_after_done:
            _set_task_progress(task_id, "snapshotting", 90, "產生截圖與裁切")
            report.engine_stats["artifact_timings_seconds"] = _generate_review_artifacts(
                task_id, old_path, new_path, report
            )

        report = save_analysis_report_state(task_id, report, complete=True)
        del old_doc, new_doc

        def updater(state):
            state.status = "done"
            state.progress_percent = 100
            state.current_step = "complete"
            state.result = report
            state.result_revision += 1
            state.error_message = None

        TASK_STORE.update(task_id, updater)

        resource_log = monitor.stop(
            old_filename=old_name,
            new_filename=new_name,
            total_diffs=report.total_diffs,
        )
        try:
            save_resource_log(resource_log)
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
        fail_compare_task(task_id, message)
