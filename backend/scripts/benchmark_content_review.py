"""Compare cold/warm diff timings and content/uncertainty regression anchors.

Run the same script with PDFCHECK_BACKEND_ROOT=/app in old/new Docker images.
PDF parsing and snapshot/export time are excluded from diff-stage timings.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(os.environ.get("PDFCHECK_BACKEND_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(BACKEND))

from scripts.run_golden_benchmark import evaluate_report  # noqa: E402
from services.diff_service import clear_pixel_diff_cache, generate_diff_report  # noqa: E402
from services.evidence_service import runtime_model_manifest  # noqa: E402
from services.parser_service import clear_parse_cache, parse_pdf  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="content-review")
    parser.add_argument("--manifest", default="benchmarks/golden/v2/manifest.json")
    parser.add_argument("--save-reports", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    manifest = json.loads((args.repo_root / args.manifest).read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {"label": args.label, "timing_scope": "diff_only_excludes_parse_and_artifacts",
              "runtime": runtime_model_manifest(), "runs": []}
    result["source_sha256"] = {
        name: hashlib.sha256((BACKEND / name).read_bytes()).hexdigest()
        for name in ("services/diff_service.py", "services/evidence_service.py")
    }
    for case in manifest["cases"]:
        clear_parse_cache()
        clear_pixel_diff_cache(include_disk=True)
        old, new = (args.repo_root / case[key] for key in ("old_pdf", "new_pdf"))
        old_doc, new_doc = parse_pdf(str(old)), parse_pdf(str(new))
        for mode in ("cold", "warm"):
            started = time.perf_counter()
            preliminary = generate_diff_report("benchmark", old.name, new.name, old_doc, new_doc,
                                               str(old), str(new), include_enrichment=False)
            first_ready = time.perf_counter() - started
            report = generate_diff_report("benchmark", old.name, new.name, old_doc, new_doc,
                                          str(old), str(new), include_enrichment=True)
            elapsed = time.perf_counter() - started
            stats = report.engine_stats
            row = {
                "case": case["id"], "mode": mode,
                "preliminary_seconds": round(first_ready, 4), "complete_seconds": round(elapsed, 4),
                "total": report.total_diffs, "content": report.total_diffs-report.unresolved_region_count,
                "uncertain": report.unresolved_region_count,
                # Cached pixel metadata contains historical OCR counters.
                "ocr_process_calls": 0 if stats.get("pixel_cache_hit") else stats.get(
                    "pixel_ocr_process_calls", stats.get("pixel_ocr_calls_total", 0)),
                "ocr_cache_hits": stats.get("pixel_ocr_cache_hits", 0),
                "evaluation": evaluate_report(report, case), "warnings": report.engine_warnings,
            }
            result["runs"].append(row)
            if args.save_reports:
                target = args.output.parent / f"{args.label}-{case['id']}-{mode}.json"
                target.write_text(report.model_dump_json(indent=2))
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps(row, ensure_ascii=False), flush=True)
    if args.verify:
        assert all(
            row["evaluation"]["must_detect_recall"] == 1
            and row["evaluation"]["prohibited_false_positives"] == 0
            and row["evaluation"]["numeric_interpretation_false_positives"] == 0
            and not row["warnings"]
            for row in result["runs"]
        ), "Content review regression failed; inspect the saved JSON."


if __name__ == "__main__":
    main()
