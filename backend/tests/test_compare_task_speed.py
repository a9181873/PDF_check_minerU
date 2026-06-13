import threading

from api import routes_compare
from api.task_store import TASK_STORE
from models.diff_models import DiffReport
from services.parser_service import ParsedDocument


def _parsed_doc(engine: str = "test") -> ParsedDocument:
    return ParsedDocument(
        pages=1,
        paragraphs=[],
        tables=[],
        raw_json={"engine": engine},
        is_image_pdf=True,
    )


def test_parse_pdf_pair_runs_old_and_new_in_parallel(monkeypatch):
    task_id = "parallel-parse-test"
    TASK_STORE.create(task_id)
    barrier = threading.Barrier(2)

    def fake_parse_pdf(path: str) -> ParsedDocument:
        barrier.wait(timeout=2)
        return _parsed_doc(engine=path)

    monkeypatch.setattr(routes_compare.settings, "parallel_pdf_parse", True)
    monkeypatch.setattr(routes_compare, "parse_pdf", fake_parse_pdf)

    try:
        old_doc, new_doc, timings = routes_compare._parse_pdf_pair(task_id, "old.pdf", "new.pdf")
    finally:
        TASK_STORE.delete(task_id)

    assert old_doc.raw_json["engine"] == "old.pdf"
    assert new_doc.raw_json["engine"] == "new.pdf"
    assert timings["parse_total_seconds"] >= 0
    assert "parse_old_seconds" in timings
    assert "parse_new_seconds" in timings


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

    monkeypatch.setattr(routes_compare.settings, "parallel_pdf_parse", False)
    monkeypatch.setattr(routes_compare.settings, "postprocess_artifacts_after_done", True)
    monkeypatch.setattr(routes_compare, "parse_pdf", lambda path: _parsed_doc(engine=path))
    monkeypatch.setattr(routes_compare, "save_markdown", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes_compare, "save_markdown_paths", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes_compare, "update_comparison_status", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes_compare, "save_comparison_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(routes_compare, "generate_diff_report", fake_generate_diff_report)
    monkeypatch.setattr(routes_compare, "save_diff_report", lambda _task_id, report: saved_reports.append(report))
    monkeypatch.setattr(routes_compare, "_start_review_artifact_generation", fake_start_artifacts)
    monkeypatch.setattr("services.resource_monitor.ResourceMonitor", FakeMonitor)
    monkeypatch.setattr("services.resource_monitor.save_resource_log", lambda *_args, **_kwargs: None)

    try:
        routes_compare._run_compare_task(
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
    assert report.engine_stats["pipeline_options"]["parallel_pdf_parse"] is False
    assert report.engine_stats["pipeline_options"]["postprocess_artifacts_after_done"] is True
    assert report.engine_stats["pipeline_timings_seconds"]["report_ready_seconds"] >= 0
    assert ("artifacts_started", "done") in events
