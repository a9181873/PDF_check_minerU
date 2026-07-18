import threading

from api.task_store import TASK_STORE
from models.diff_models import DiffReport
from services import compare_orchestrator
from services.parser_service import ParsedDocument


def _parsed_doc(engine: str = "test") -> ParsedDocument:
    return ParsedDocument(
        pages=1,
        paragraphs=[],
        tables=[],
        raw_json={"engine": engine},
        is_image_pdf=True,
    )


def test_parse_pdf_pair_runs_old_and_new_sequentially_for_pymupdf_safety(monkeypatch):
    task_id = "sequential-parse-test"
    TASK_STORE.create(task_id)
    calls = []

    def fake_parse_pdf(path: str) -> ParsedDocument:
        calls.append(path)
        return _parsed_doc(engine=path)

    monkeypatch.setattr(compare_orchestrator, "parse_pdf", fake_parse_pdf)

    try:
        old_doc, new_doc, timings = compare_orchestrator.parse_pdf_pair(task_id, "old.pdf", "new.pdf")
    finally:
        TASK_STORE.delete(task_id)

    assert old_doc.raw_json["engine"] == "old.pdf"
    assert new_doc.raw_json["engine"] == "new.pdf"
    assert calls == ["old.pdf", "new.pdf"]
    assert timings["parse_total_seconds"] >= 0
    assert "parse_old_seconds" in timings
    assert "parse_new_seconds" in timings


def test_review_artifacts_stay_on_compare_worker_thread(monkeypatch):
    caller_thread = threading.get_ident()
    observed_threads: list[int] = []

    def fake_generate(*_args):
        observed_threads.append(threading.get_ident())

    monkeypatch.setattr(compare_orchestrator, "_generate_review_artifacts", fake_generate)

    compare_orchestrator._start_review_artifact_generation(
        "task-id", "old.pdf", "new.pdf", object()
    )

    assert observed_threads == [caller_thread]


def test_compare_task_records_speed_options_and_starts_artifacts_after_done(monkeypatch):
    task_id = "speed-options-test"
    TASK_STORE.create(task_id)
    events: list[tuple[str, str]] = []
    saved_reports: list[DiffReport] = []

    class FakeMonitor:
        def __init__(self, task_id: str):
            self.task_id = task_id

        def start(self):
            events.append(("monitor_start", ""))

        def stop(self, **kwargs):
            events.append(("monitor_stop", ""))
            return object()

    def fake_start_artifacts(task_id: str, *_args):
        state = TASK_STORE.get(task_id)
        events.append(("artifacts_started", state.status if state else "missing"))

    def fake_generate_diff_report(**kwargs) -> DiffReport:
        return DiffReport(
            project_id=kwargs["project_id"],
            old_filename=kwargs["old_filename"],
            new_filename=kwargs["new_filename"],
            created_at="2026-06-13T00:00:00+00:00",
            total_diffs=0,
            items=[],
            engine_stats={},
        )

    monkeypatch.setattr(compare_orchestrator.settings, "postprocess_artifacts_after_done", True)
    monkeypatch.setattr(compare_orchestrator, "parse_pdf", lambda path: _parsed_doc(engine=path))
    monkeypatch.setattr(compare_orchestrator, "save_markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(compare_orchestrator, "save_markdown_paths", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(compare_orchestrator, "update_comparison_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(compare_orchestrator, "save_comparison_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(compare_orchestrator, "generate_diff_report", fake_generate_diff_report)
    def fake_save_report(_task_id, report, *, complete=False):
        if complete:
            saved_reports.append(report)
        return report

    monkeypatch.setattr(compare_orchestrator, "save_analysis_report_state", fake_save_report)
    monkeypatch.setattr(compare_orchestrator, "_start_review_artifact_generation", fake_start_artifacts)
    monkeypatch.setattr("services.resource_monitor.ResourceMonitor", FakeMonitor)
    monkeypatch.setattr("services.resource_monitor.save_resource_log", lambda *_args, **_kwargs: None)

    try:
        compare_orchestrator.run_compare_task(
            task_id=task_id,
            project_id="default",
            case_number=None,
            old_path="old.pdf",
            new_path="new.pdf",
            old_name="old.pdf",
            new_name="new.pdf",
        )
    finally:
        TASK_STORE.delete(task_id)

    assert saved_reports
    report = saved_reports[0]
    assert report.engine_stats["pipeline_options"]["pdf_parse_strategy"] == "sequential_pymupdf_safe"
    assert report.engine_stats["pipeline_options"]["postprocess_artifacts_after_done"] is True
    assert report.engine_stats["pipeline_timings_seconds"]["report_ready_seconds"] >= 0
    assert ("artifacts_started", "done") in events
