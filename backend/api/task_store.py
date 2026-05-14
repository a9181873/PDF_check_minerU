import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock

from models.diff_models import DiffReport


@dataclass
class TaskState:
    status: str
    progress_percent: int
    current_step: str
    error_message: str | None = None
    result: DiffReport | None = None
    finished_at: float | None = None


_MAX_TASKS = 500            # hard cap on in-memory entries
_TTL_SECONDS = 24 * 3600    # drop finished tasks after 24h


class InMemoryTaskStore:
    def __init__(self):
        self._tasks: dict[str, TaskState] = {}
        self._lock = Lock()

    def _gc_locked(self) -> None:
        """Drop expired finished tasks; if still over cap, drop oldest finished first."""
        now = time.time()
        expired = [
            tid for tid, s in self._tasks.items()
            if s.finished_at and (now - s.finished_at) > _TTL_SECONDS
        ]
        for tid in expired:
            self._tasks.pop(tid, None)
        if len(self._tasks) > _MAX_TASKS:
            finished = sorted(
                ((tid, s) for tid, s in self._tasks.items() if s.finished_at),
                key=lambda kv: kv[1].finished_at or 0.0,
            )
            for tid, _ in finished[: len(self._tasks) - _MAX_TASKS]:
                self._tasks.pop(tid, None)

    def create(self, task_id: str) -> TaskState:
        state = TaskState(status="parsing", progress_percent=0, current_step="queued")
        with self._lock:
            self._gc_locked()
            self._tasks[task_id] = state
        return state

    def get(self, task_id: str) -> TaskState | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, updater: Callable[[TaskState], None]) -> TaskState | None:
        with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                return None
            updater(state)
            # Stamp finished_at when status transitions to a terminal state
            if state.status in ("done", "error") and state.finished_at is None:
                state.finished_at = time.time()
            return state

    def delete(self, task_id: str) -> None:
        with self._lock:
            self._tasks.pop(task_id, None)


TASK_STORE = InMemoryTaskStore()
