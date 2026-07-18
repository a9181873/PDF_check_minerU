"""Bounded in-process runner for CPU-heavy comparison jobs."""

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore

from config import settings
from services.compare_orchestrator import run_compare_task

_logger = logging.getLogger(__name__)


class CompareJobRunner:
    def __init__(self, max_workers: int, max_pending: int):
        if max_workers != 1:
            _logger.warning(
                "Thread-based PDF comparison concurrency is fixed at 1 for PyMuPDF safety; requested=%s",
                max_workers,
            )
        safe_workers = 1
        self._executor = ThreadPoolExecutor(
            max_workers=safe_workers,
            thread_name_prefix="pdf-compare",
        )
        self._capacity = BoundedSemaphore(safe_workers + max_pending)

    def submit(
        self,
        task_id: str,
        project_id: str,
        case_number: str | None,
        old_path: str,
        new_path: str,
        old_name: str,
        new_name: str,
    ) -> bool:
        if not self._capacity.acquire(blocking=False):
            return False

        try:
            future = self._executor.submit(
                run_compare_task,
                task_id,
                project_id,
                case_number,
                old_path,
                new_path,
                old_name,
                new_name,
            )
        except Exception:
            self._capacity.release()
            raise

        future.add_done_callback(self._release_capacity)
        return True

    def _release_capacity(self, future: Future[None]) -> None:
        self._capacity.release()
        if future.cancelled():
            return
        exception = future.exception()
        if exception is not None:
            _logger.error(
                "Unhandled comparison worker failure",
                exc_info=(type(exception), exception, exception.__traceback__),
            )

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)


COMPARE_JOB_RUNNER = CompareJobRunner(
    max_workers=settings.compare_max_concurrency,
    max_pending=settings.compare_max_pending_tasks,
)
