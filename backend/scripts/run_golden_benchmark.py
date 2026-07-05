#!/usr/bin/env python3
"""Run the same end-to-end golden benchmark on Mac/OCI/onsite hosts."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from config import settings  # noqa: E402
from models.diff_models import AnalysisStage, AnalysisStatus, DiffReport  # noqa: E402
from services.diff_service import clear_pixel_diff_cache, generate_diff_report  # noqa: E402
from services.parser_service import clear_parse_cache, parse_pdf  # noqa: E402
from services.resource_monitor import ResourceMonitor  # noqa: E402


def percentile(values: list[float], value: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * value
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction, 4)


def hardware_snapshot(host_label: str | None) -> dict[str, Any]:
    info: dict[str, Any] = {
        "host_label": host_label or socket.gethostname(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
    }
    try:
        import psutil

        vm = psutil.virtual_memory()
        info.update(
            {
                "physical_cores": psutil.cpu_count(logical=False),
                "logical_cores": psutil.cpu_count(logical=True),
                "memory_total_gb": round(vm.total / 1024**3, 2),
            }
        )
    except ImportError:
        info["resource_warning"] = "psutil unavailable"
    return info


def _item_text(item) -> str:
    return " | ".join(filter(None, (item.context, item.old_value, item.new_value)))


def _matches(item, expectation: dict[str, Any]) -> bool:
    bbox = item.new_bbox or item.old_bbox
    if expectation.get("page") and (not bbox or bbox.page != expectation["page"]):
        return False
    fields = (
        ("old_regex", item.old_value or ""),
        ("new_regex", item.new_value or ""),
        ("context_regex", item.context or ""),
    )
    for key, value in fields:
        pattern = expectation.get(key)
        if pattern and not re.search(pattern, value, re.IGNORECASE):
            return False
    allowed_lanes = expectation.get("review_lanes")
    if allowed_lanes and item.review_lane.value not in allowed_lanes:
        return False
    return True


def evaluate_report(report: DiffReport, case: dict[str, Any]) -> dict[str, Any]:
    detections = []
    for expected in case.get("must_detect", []):
        hits = [item.id for item in report.items if _matches(item, expected)]
        detections.append({"id": expected["id"], "passed": bool(hits), "hits": hits})

    prohibited = []
    for pattern in case.get("must_not_detect", []):
        hits = [item.id for item in report.items if re.search(pattern, _item_text(item), re.IGNORECASE)]
        prohibited.append({"pattern": pattern, "passed": not hits, "hits": hits})

    must_detect_passed = sum(row["passed"] for row in detections)
    total_expected = len(detections)
    return {
        "must_detect": detections,
        "must_not_detect": prohibited,
        "must_detect_passed": must_detect_passed,
        "must_detect_total": total_expected,
        "must_detect_recall": round(must_detect_passed / total_expected, 4) if total_expected else 1.0,
        "prohibited_false_positives": sum(not row["passed"] for row in prohibited),
        "material_visual_suppressed": int(report.engine_stats.get("material_visual_suppressed", 0)),
        "unresolved_region_count": report.unresolved_region_count,
    }


def evaluate_preliminary_region_coverage(
    report: DiffReport, case: dict[str, Any]
) -> dict[str, Any]:
    rows = []
    for expected in case.get("must_detect", []):
        page = expected.get("page")
        hits = [
            item.id
            for item in report.items
            if page is None
            or ((item.new_bbox or item.old_bbox) and (item.new_bbox or item.old_bbox).page == page)
        ]
        rows.append({"id": expected["id"], "passed": bool(hits), "hits": hits})
    passed = sum(row["passed"] for row in rows)
    return {
        "regions": rows,
        "passed": passed,
        "total": len(rows),
        "region_recall": round(passed / len(rows), 4) if rows else 1.0,
    }


def _compact_items(report: DiffReport) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "candidate_id": item.candidate_id,
            "type": item.diff_type.value,
            "lane": item.review_lane.value,
            "risk": item.risk_level.value,
            "page": (item.new_bbox or item.old_bbox).page if (item.new_bbox or item.old_bbox) else None,
            "old_value": item.old_value,
            "new_value": item.new_value,
            "context": item.context,
        }
        for item in report.items
    ]


def run_once(case: dict[str, Any], repo_root: Path, run_id: str) -> dict[str, Any]:
    old_path = repo_root / case["old_pdf"]
    new_path = repo_root / case["new_pdf"]
    if not old_path.exists() or not new_path.exists():
        raise FileNotFoundError(f"Missing golden PDFs: {old_path} / {new_path}")

    monitor = ResourceMonitor(run_id, interval=0.1)
    monitor.start()
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        old_future = pool.submit(parse_pdf, str(old_path))
        new_future = pool.submit(parse_pdf, str(new_path))
        old_doc, new_doc = old_future.result(), new_future.result()
    parse_seconds = time.perf_counter() - started

    prelim_started = time.perf_counter()
    preliminary = generate_diff_report(
        project_id="benchmark",
        old_filename=old_path.name,
        new_filename=new_path.name,
        old_doc=old_doc,
        new_doc=new_doc,
        old_pdf_path=str(old_path),
        new_pdf_path=str(new_path),
        include_enrichment=False,
    )
    preliminary_seconds = time.perf_counter() - prelim_started
    initial_ready_seconds = time.perf_counter() - started

    enrichment_enabled = bool(old_doc.is_image_pdf or new_doc.is_image_pdf)
    if enrichment_enabled:
        enrich_started = time.perf_counter()
        report = generate_diff_report(
            project_id="benchmark",
            old_filename=old_path.name,
            new_filename=new_path.name,
            old_doc=old_doc,
            new_doc=new_doc,
            old_pdf_path=str(old_path),
            new_pdf_path=str(new_path),
            include_enrichment=True,
        )
        enrichment_seconds = time.perf_counter() - enrich_started
    else:
        report = preliminary
        report.analysis_status = AnalysisStatus.COMPLETE
        for item in report.items:
            item.analysis_stage = AnalysisStage.FINAL
        enrichment_seconds = 0.0

    complete_seconds = time.perf_counter() - started
    resource = monitor.stop(old_path.name, new_path.name, report.total_diffs)
    return {
        "run_id": run_id,
        "case_id": case["id"],
        "pages": max(old_doc.pages, new_doc.pages),
        "input_pages": old_doc.pages + new_doc.pages,
        "timings": {
            "parse_seconds": round(parse_seconds, 4),
            "preliminary_diff_seconds": round(preliminary_seconds, 4),
            "initial_ready_seconds": round(initial_ready_seconds, 4),
            "enrichment_seconds": round(enrichment_seconds, 4),
            "complete_seconds": round(complete_seconds, 4),
        },
        "resources": {
            "peak_memory_mb": resource.peak_memory_mb,
            "avg_cpu_percent": resource.avg_cpu_percent,
            "peak_cpu_percent": resource.peak_cpu_percent,
        },
        "cache": {
            "old_parser_hit": bool((old_doc.raw_json.get("routing") or {}).get("cache_hit")),
            "new_parser_hit": bool((new_doc.raw_json.get("routing") or {}).get("cache_hit")),
            "pixel_hit": bool(report.engine_stats.get("pixel_cache_hit")),
        },
        "total_diffs": report.total_diffs,
        "preliminary_evaluation": evaluate_preliminary_region_coverage(preliminary, case),
        "evaluation": evaluate_report(report, case),
        "items": _compact_items(report),
        "engine_stats": report.engine_stats,
        "engine_warnings": report.engine_warnings,
    }


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    initial = [row["timings"]["initial_ready_seconds"] for row in runs]
    complete = [row["timings"]["complete_seconds"] for row in runs]
    expected = sum(row["evaluation"]["must_detect_total"] for row in runs)
    passed = sum(row["evaluation"]["must_detect_passed"] for row in runs)
    preliminary_expected = sum(row["preliminary_evaluation"]["total"] for row in runs)
    preliminary_passed = sum(row["preliminary_evaluation"]["passed"] for row in runs)
    return {
        "runs": len(runs),
        "page_pairs": sum(row["pages"] for row in runs),
        "input_pages": sum(row["input_pages"] for row in runs),
        "initial_ready_p50_seconds": percentile(initial, 0.5),
        "initial_ready_p95_seconds": percentile(initial, 0.95),
        "complete_p50_seconds": percentile(complete, 0.5),
        "complete_p95_seconds": percentile(complete, 0.95),
        "complete_mean_seconds": round(statistics.mean(complete), 4) if complete else 0.0,
        "peak_memory_mb": max((row["resources"]["peak_memory_mb"] for row in runs), default=0.0),
        "peak_cpu_percent": max((row["resources"]["peak_cpu_percent"] for row in runs), default=0.0),
        "must_detect_recall": round(passed / expected, 4) if expected else 1.0,
        "preliminary_region_recall": (
            round(preliminary_passed / preliminary_expected, 4)
            if preliminary_expected else 1.0
        ),
        "prohibited_false_positives": sum(
            row["evaluation"]["prohibited_false_positives"] for row in runs
        ),
        "material_visual_suppressed": sum(
            row["evaluation"]["material_visual_suppressed"] for row in runs
        ),
        "sla": {
            "initial_ready_p95_le_15s": percentile(initial, 0.95) <= 15.0,
            "complete_p95_le_90s": percentile(complete, 0.95) <= 90.0,
            "known_critical_recall_100pct": passed == expected,
            "preliminary_region_recall_100pct": preliminary_passed == preliminary_expected,
        },
    }


def write_markdown(result: dict[str, Any], path: Path) -> None:
    lines = [
        f"# PDF/OCR 黃金效能基準：{result['hardware']['host_label']}",
        "",
        f"- 執行時間：{result['created_at']}",
        f"- 主機：`{result['hardware']['platform']}` / `{result['hardware']['machine']}`",
        f"- CPU/RAM：{result['hardware'].get('logical_cores')} threads / {result['hardware'].get('memory_total_gb')} GB",
        "",
        "## 摘要",
        "",
        "| 模式 | Runs | 初步 P95 | 完整 P95 | 初步區域召回 | 完整必抓召回 | 禁止誤報 | 視覺靜默抑制 | 峰值 RAM |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, block in result["modes"].items():
        s = block["summary"]
        lines.append(
            f"| {mode} | {s['runs']} | {s['initial_ready_p95_seconds']:.2f}s | {s['complete_p95_seconds']:.2f}s | "
            f"{s['preliminary_region_recall']:.1%} | {s['must_detect_recall']:.1%} | "
            f"{s['prohibited_false_positives']} | {s['material_visual_suppressed']} | {s['peak_memory_mb']:.1f}MB |"
        )
    lines.extend(["", "> 六對樣本只代表既有案例回歸，不代表母體 OCR 準確率。", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "benchmarks/golden/v1/manifest.json")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--mode", choices=("cold", "warm", "both"), default="both")
    parser.add_argument("--host-label")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result: dict[str, Any] = {
        "schema_version": 1,
        "benchmark": manifest["name"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hardware": hardware_snapshot(args.host_label),
        "settings": {
            "image_text_recall": settings.enable_image_text_recall,
            "paddle_ocr_experiment": settings.enable_paddle_ocr_experiment,
            "table_parser_strategy": settings.table_parser_strategy,
        },
        "modes": {},
    }

    modes = ("cold", "warm") if args.mode == "both" else (args.mode,)
    for mode in modes:
        runs: list[dict[str, Any]] = []
        for case in manifest["cases"]:
            if mode == "warm":
                clear_parse_cache()
                clear_pixel_diff_cache()
                run_once(case, args.repo_root, f"warmup-{case['id']}")
            for index in range(args.repeat):
                if mode == "cold":
                    clear_parse_cache()
                    clear_pixel_diff_cache(include_disk=True)
                runs.append(run_once(case, args.repo_root, f"{mode}-{case['id']}-{index + 1}"))
        result["modes"][mode] = {"summary": summarize(runs), "runs": runs}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(result, args.output.with_suffix(".md"))
    print(json.dumps({mode: block["summary"] for mode, block in result["modes"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
