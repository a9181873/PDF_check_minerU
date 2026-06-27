import inspect
import threading

from api import (
    routes_archive,
    routes_auth,
    routes_checklist,
    routes_compare,
    routes_export,
    routes_project,
    routes_review,
)
from services import compare_job_runner


def test_sync_database_routes_are_not_coroutines():
    handlers = (
        routes_auth.login,
        routes_auth.admin_list_users,
        routes_compare.upload_compare_files,
        routes_compare.get_compare_status,
        routes_compare.get_compare_result,
        routes_project.list_projects_api,
        routes_review.confirm_diff,
        routes_export.export_report,
        routes_archive.get_history,
        routes_checklist.import_checklist_api,
    )
    assert all(not inspect.iscoroutinefunction(handler) for handler in handlers)


def test_compare_job_runner_rejects_work_over_capacity(monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def blocking_compare(*_args):
        started.set()
        release.wait(timeout=2)

    monkeypatch.setattr(compare_job_runner, "run_compare_task", blocking_compare)
    runner = compare_job_runner.CompareJobRunner(max_workers=1, max_pending=0)

    try:
        assert runner.submit("task-1", "default", None, "old", "new", "old.pdf", "new.pdf")
        assert started.wait(timeout=1)
        assert not runner.submit("task-2", "default", None, "old", "new", "old.pdf", "new.pdf")
    finally:
        release.set()
        runner.shutdown()
