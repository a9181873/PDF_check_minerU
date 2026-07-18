"""Hardware resource monitoring for PDF comparison tasks.

Records CPU%, memory usage, and elapsed time per comparison task.
Results are stored in SQLite and exposed via API for capacity planning.
"""

import os
import platform
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ResourceSnapshot:
    timestamp: str
    cpu_percent: float
    memory_mb: float
    memory_percent: float


@dataclass
class TaskResourceLog:
    task_id: str
    started_at: str
    finished_at: str = ""
    elapsed_seconds: float = 0.0
    peak_memory_mb: float = 0.0
    avg_cpu_percent: float = 0.0
    peak_cpu_percent: float = 0.0
    old_filename: str = ""
    new_filename: str = ""
    total_diffs: int = 0
    system_info: dict = field(default_factory=dict)
    snapshots: list[ResourceSnapshot] = field(default_factory=list)


def _get_system_info() -> dict:
    """Collect static system information."""
    info = {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "processor": platform.processor() or "unknown",
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        info["total_memory_gb"] = round(vm.total / (1024 ** 3), 1)
    except ImportError:
        info["total_memory_gb"] = "unknown (psutil not installed)"
    return info


class ResourceMonitor:
    """Monitors CPU and memory in a background thread during a task."""

    def __init__(self, task_id: str, interval: float = 2.0):
        self.task_id = task_id
        self.interval = interval
        self._log = TaskResourceLog(
            task_id=task_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            system_info=_get_system_info(),
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._has_psutil = False
        self._tracked_processes: dict[int, object] = {}
        try:
            import psutil  # noqa: F401
            self._has_psutil = True
        except ImportError:
            pass

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self, old_filename: str = "", new_filename: str = "", total_diffs: int = 0):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._log.finished_at = datetime.now(timezone.utc).isoformat()
        start_dt = datetime.fromisoformat(self._log.started_at)
        end_dt = datetime.fromisoformat(self._log.finished_at)
        self._log.elapsed_seconds = round((end_dt - start_dt).total_seconds(), 1)
        self._log.old_filename = old_filename
        self._log.new_filename = new_filename
        self._log.total_diffs = total_diffs

        if self._log.snapshots:
            mems = [s.memory_mb for s in self._log.snapshots]
            cpus = [s.cpu_percent for s in self._log.snapshots]
            self._log.peak_memory_mb = round(max(mems), 1)
            self._log.avg_cpu_percent = round(sum(cpus) / len(cpus), 1)
            self._log.peak_cpu_percent = round(max(cpus), 1)

        return self._log

    def _sample_loop(self):
        if not self._has_psutil:
            return
        import psutil

        root = psutil.Process(os.getpid())

        def refresh_process_tree() -> list:
            live = [root]
            try:
                live.extend(root.children(recursive=True))
            except (psutil.Error, PermissionError):
                pass
            live_by_pid = {}
            for proc in live:
                try:
                    if proc.is_running():
                        live_by_pid[proc.pid] = proc
                except (psutil.Error, PermissionError):
                    continue
            for pid, proc in live_by_pid.items():
                if pid not in self._tracked_processes:
                    try:
                        proc.cpu_percent(interval=None)
                    except (psutil.Error, PermissionError):
                        continue
                    self._tracked_processes[pid] = proc
            self._tracked_processes = {
                pid: proc for pid, proc in self._tracked_processes.items() if pid in live_by_pid
            }
            return list(self._tracked_processes.values())

        refresh_process_tree()
        self._stop_event.wait(min(0.5, self.interval))
        while not self._stop_event.is_set():
            try:
                processes = refresh_process_tree()
                cpu = 0.0
                rss = 0
                for proc in processes:
                    try:
                        cpu += proc.cpu_percent(interval=None)
                        rss += proc.memory_info().rss
                    except (psutil.Error, PermissionError):
                        continue
                mem_mb = round(rss / (1024 ** 2), 1)
                vm = psutil.virtual_memory()
                mem_pct = round(rss / vm.total * 100, 1)
                snap = ResourceSnapshot(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    cpu_percent=cpu,
                    memory_mb=mem_mb,
                    memory_percent=mem_pct,
                )
                self._log.snapshots.append(snap)
            except Exception:
                pass
            self._stop_event.wait(self.interval)


# ── Persistence ──────────────────────────────────────────────────────────────

import json


def save_resource_log(log: TaskResourceLog) -> None:
    """Persist a resource log entry to SQLite."""
    from models.database import get_connection, utc_now_iso
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO resource_logs
               (task_id, started_at, finished_at, elapsed_seconds,
                peak_memory_mb, avg_cpu_percent, peak_cpu_percent,
                old_filename, new_filename, total_diffs,
                system_info_json, snapshots_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                log.task_id,
                log.started_at,
                log.finished_at,
                log.elapsed_seconds,
                log.peak_memory_mb,
                log.avg_cpu_percent,
                log.peak_cpu_percent,
                log.old_filename,
                log.new_filename,
                log.total_diffs,
                json.dumps(log.system_info, ensure_ascii=False),
                json.dumps(
                    [{"ts": s.timestamp, "cpu": s.cpu_percent, "mem_mb": s.memory_mb, "mem_pct": s.memory_percent}
                     for s in log.snapshots],
                    ensure_ascii=False,
                ),
                utc_now_iso(),
            ),
        )


def list_resource_logs(limit: int = 50) -> list[dict]:
    """Retrieve recent resource logs."""
    from models.database import get_connection
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT task_id, started_at, finished_at, elapsed_seconds,
                      peak_memory_mb, avg_cpu_percent, peak_cpu_percent,
                      old_filename, new_filename, total_diffs,
                      system_info_json, created_at
               FROM resource_logs ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["system_info"] = json.loads(d.pop("system_info_json", "{}"))
        results.append(d)
    return results


def get_resource_log_detail(task_id: str) -> dict | None:
    """Get full detail including snapshots."""
    from models.database import get_connection
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM resource_logs WHERE task_id = ?", (task_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["system_info"] = json.loads(d.pop("system_info_json", "{}"))
    d["snapshots"] = json.loads(d.pop("snapshots_json", "[]"))
    return d
