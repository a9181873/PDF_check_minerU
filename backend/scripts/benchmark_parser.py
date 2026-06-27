#!/usr/bin/env python3
"""Benchmark PDF parsing performance and resource usage.

Usage example:
  .venv/bin/python scripts/benchmark_parser.py \
    --pdf ../samples/台灣人壽金利樂利率變動型養老保險.pdf \
    --pdf ../samples/台灣人壽臻鑽旺旺變額萬能壽險.pdf \
    --repeat 2 --warmup 1
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import socket
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import psutil

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.parser_service import clear_parse_cache, parse_pdf  # noqa: E402


@dataclass
class SamplePoint:
    ts: float
    rss_bytes: int
    cpu_percent: float


@dataclass
class RunRecord:
    run_index: int
    started_at: str
    finished_at: str
    elapsed_sec: float
    success: bool
    error: str | None
    engine: str | None
    table_engine: str | None
    cache_hit: bool | None
    pages: int | None
    paragraphs: int | None
    tables: int | None
    sample_count: int
    peak_rss_bytes: int
    avg_rss_bytes: int
    peak_cpu_percent: float
    avg_cpu_percent: float


class ResourceMonitor:
    def __init__(self, pid: int, interval_sec: float = 0.1):
        self._proc = psutil.Process(pid)
        self._interval_sec = interval_sec
        self._stop = threading.Event()
        self.samples: list[SamplePoint] = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._tracked: dict[int, psutil.Process] = {}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _run(self) -> None:
        def process_tree() -> list[psutil.Process]:
            processes = [self._proc]
            try:
                processes.extend(self._proc.children(recursive=True))
            except psutil.Error:
                pass
            live = {proc.pid: proc for proc in processes if proc.is_running()}
            for pid, proc in live.items():
                if pid not in self._tracked:
                    try:
                        proc.cpu_percent(interval=None)
                    except psutil.Error:
                        continue
                    self._tracked[pid] = proc
            self._tracked = {pid: proc for pid, proc in self._tracked.items() if pid in live}
            return list(self._tracked.values())

        process_tree()
        while not self._stop.is_set():
            try:
                rss = 0
                cpu = 0.0
                for proc in process_tree():
                    try:
                        rss += proc.memory_info().rss
                        cpu += proc.cpu_percent(interval=None)
                    except psutil.Error:
                        continue
            except psutil.Error:
                break
            self.samples.append(SamplePoint(ts=time.time(), rss_bytes=int(rss), cpu_percent=float(cpu)))
            time.sleep(self._interval_sec)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_hardware_snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    freq = psutil.cpu_freq()

    torch_info: dict[str, Any] = {}
    try:
        import torch  # type: ignore

        torch_info = {
            "torch_version": getattr(torch, "__version__", None),
            "cuda_available": bool(torch.cuda.is_available()),
            "mps_available": bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()),
        }
    except Exception as exc:  # pragma: no cover - optional dependency
        torch_info = {"torch_error": str(exc)}

    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_physical_cores": psutil.cpu_count(logical=False),
        "cpu_logical_cores": psutil.cpu_count(logical=True),
        "cpu_freq_mhz_current": getattr(freq, "current", None),
        "cpu_freq_mhz_max": getattr(freq, "max", None),
        "memory_total_bytes": int(vm.total),
        "memory_available_bytes": int(vm.available),
        "ocr_langs": os.getenv("OCR_LANGS", "eng"),
        **torch_info,
    }


def summarize_samples(samples: list[SamplePoint]) -> tuple[int, int, int, float, float]:
    if not samples:
        return 0, 0, 0, 0.0, 0.0

    rss_values = [s.rss_bytes for s in samples]
    cpu_values = [s.cpu_percent for s in samples]
    return (
        len(samples),
        max(rss_values),
        int(mean(rss_values)),
        max(cpu_values),
        float(mean(cpu_values)),
    )


def run_single_parse(pdf_path: Path, run_index: int, sample_interval_sec: float) -> RunRecord:
    started = utc_now_iso()
    t0 = time.perf_counter()
    monitor = ResourceMonitor(os.getpid(), interval_sec=sample_interval_sec)
    monitor.start()

    success = True
    error = None
    engine = None
    table_engine = None
    cache_hit = None
    pages = None
    paragraphs = None
    tables = None

    try:
        parsed = parse_pdf(str(pdf_path))
        engine = str(parsed.raw_json.get("engine")) if parsed.raw_json else None
        table_engine = str(parsed.raw_json.get("table_engine")) if parsed.raw_json.get("table_engine") else None
        cache_hit = bool((parsed.raw_json.get("routing") or {}).get("cache_hit", False))
        pages = parsed.pages
        paragraphs = len(parsed.paragraphs)
        tables = len(parsed.tables)
    except Exception as exc:  # pragma: no cover - runtime failures
        success = False
        error = str(exc)
    finally:
        monitor.stop()

    elapsed = time.perf_counter() - t0
    finished = utc_now_iso()
    sample_count, peak_rss, avg_rss, peak_cpu, avg_cpu = summarize_samples(monitor.samples)

    return RunRecord(
        run_index=run_index,
        started_at=started,
        finished_at=finished,
        elapsed_sec=round(elapsed, 4),
        success=success,
        error=error,
        engine=engine,
        table_engine=table_engine,
        cache_hit=cache_hit,
        pages=pages,
        paragraphs=paragraphs,
        tables=tables,
        sample_count=sample_count,
        peak_rss_bytes=peak_rss,
        avg_rss_bytes=avg_rss,
        peak_cpu_percent=round(peak_cpu, 2),
        avg_cpu_percent=round(avg_cpu, 2),
    )


def summarize_runs(runs: list[RunRecord]) -> dict[str, Any]:
    if not runs:
        return {}
    ok_runs = [r for r in runs if r.success]
    target = ok_runs if ok_runs else runs

    return {
        "runs_total": len(runs),
        "runs_success": len(ok_runs),
        "elapsed_sec_avg": round(mean(r.elapsed_sec for r in target), 4),
        "elapsed_sec_min": round(min(r.elapsed_sec for r in target), 4),
        "elapsed_sec_max": round(max(r.elapsed_sec for r in target), 4),
        "peak_rss_mb_max": round(max(r.peak_rss_bytes for r in target) / (1024 * 1024), 2),
        "avg_cpu_percent_avg": round(mean(r.avg_cpu_percent for r in target), 2),
        "peak_cpu_percent_max": round(max(r.peak_cpu_percent for r in target), 2),
        "engine_set": sorted({r.engine for r in target if r.engine}),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark PDF parser performance")
    parser.add_argument(
        "--pdf",
        dest="pdfs",
        action="append",
        required=True,
        help="Path to PDF file. Repeat --pdf for multiple files.",
    )
    parser.add_argument("--repeat", type=int, default=3, help="Measured runs per PDF (default: 3)")
    parser.add_argument("--warmup", type=int, default=1, help="Warm-up runs before measurement (default: 1)")
    parser.add_argument(
        "--sample-interval",
        type=float,
        default=0.1,
        help="Resource sampling interval in seconds (default: 0.1)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "benchmarks",
        help="Output directory for benchmark reports",
    )
    parser.add_argument("--tag", type=str, default="", help="Optional tag for output file names")
    parser.add_argument(
        "--cache-mode",
        choices=("cold", "warm"),
        default="cold",
        help="Clear parser cache before each run, or measure warm-cache behavior",
    )
    return parser.parse_args()


def write_reports(report: dict[str, Any], output_dir: Path, tag: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""

    json_path = output_dir / f"parse_benchmark_{stamp}{suffix}.json"
    csv_path = output_dir / f"parse_benchmark_{stamp}{suffix}.csv"

    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for file_result in report["files"]:
        pdf_name = file_result["pdf"]
        for run in file_result["runs"]:
            row = {"pdf": pdf_name, **run}
            rows.append(row)

    if rows:
        fieldnames = list(rows[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    return json_path, csv_path


def main() -> int:
    args = parse_args()

    pdf_paths = [Path(p).expanduser().resolve() for p in args.pdfs]
    missing = [str(p) for p in pdf_paths if not p.exists()]
    if missing:
        print("Missing PDF files:")
        for p in missing:
            print(f"  - {p}")
        return 1

    report: dict[str, Any] = {
        "created_at": utc_now_iso(),
        "benchmark_config": {
            "repeat": args.repeat,
            "warmup": args.warmup,
            "sample_interval_sec": args.sample_interval,
            "tag": args.tag,
            "cache_mode": args.cache_mode,
        },
        "hardware": collect_hardware_snapshot(),
        "files": [],
    }

    for pdf_path in pdf_paths:
        print(f"\n=== Benchmarking: {pdf_path.name} ===")
        for i in range(args.warmup):
            print(f"Warmup {i + 1}/{args.warmup} ...")
            if args.cache_mode == "cold":
                clear_parse_cache()
            _ = run_single_parse(pdf_path, run_index=-(i + 1), sample_interval_sec=args.sample_interval)

        runs: list[RunRecord] = []
        for i in range(args.repeat):
            print(f"Run {i + 1}/{args.repeat} ...")
            if args.cache_mode == "cold":
                clear_parse_cache()
            rec = run_single_parse(pdf_path, run_index=i + 1, sample_interval_sec=args.sample_interval)
            runs.append(rec)
            print(
                "  elapsed={:.3f}s engine={} peak_rss={:.1f}MB peak_cpu={:.1f}% success={}".format(
                    rec.elapsed_sec,
                    rec.engine,
                    rec.peak_rss_bytes / (1024 * 1024),
                    rec.peak_cpu_percent,
                    rec.success,
                )
            )

        report["files"].append(
            {
                "pdf": str(pdf_path),
                "file_size_bytes": pdf_path.stat().st_size,
                "runs": [asdict(r) for r in runs],
                "summary": summarize_runs(runs),
            }
        )

    json_path, csv_path = write_reports(report, args.output_dir, args.tag)
    print("\nBenchmark reports generated:")
    print(f"  JSON: {json_path}")
    print(f"  CSV : {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
