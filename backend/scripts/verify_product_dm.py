"""Audit real product DMs without treating visual coverage as successful OCR.

Run after benchmark_content_review.py --label forward --save-reports. Uses an
isolated DATA_DIR supplied by the caller; never points this at production data.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

BACKEND = Path(os.environ.get("PDFCHECK_BACKEND_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(BACKEND))

import fitz  # noqa: E402
from models.diff_models import DiffReport, ReviewLane  # noqa: E402
from scripts.run_golden_benchmark import _matches  # noqa: E402
from services.diff_service import clear_pixel_diff_cache, generate_diff_report  # noqa: E402
from services.evidence_service import runtime_model_manifest  # noqa: E402
from services.parser_service import clear_parse_cache, parse_pdf  # noqa: E402


def content_signature(report, reverse=False):
    """Compare exact reported values, ignoring IDs, whitespace and timing."""
    result = Counter()
    for item in report.items:
        if item.review_lane != ReviewLane.CONTENT:
            continue
        old, new = item.old_value, item.new_value
        kind = item.diff_type.value
        if reverse:
            old, new = new, old
            kind = {"added": "deleted", "deleted": "added"}.get(kind, kind)
        box = item.new_bbox or item.old_bbox
        normalize = lambda text: re.sub(r"\s+", "", text or "")
        result[(box.page if box else None, kind, normalize(old), normalize(new))] += 1
    return result


def describe_signatures(signatures):
    return [{"page": key[0], "type": key[1], "old": key[2], "new": key[3], "count": count}
            for key, count in signatures.items()]


def source_revision(root):
    if revision := os.environ.get("PDFCHECK_SOURCE_REVISION"):
        return revision
    try:
        return subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable; use source_sha256"


def evaluate_content_truth(root, output, label, truth_path):
    truth = json.loads((root / truth_path).read_text())
    checks = []
    reports = {}
    for expected in truth["checks"]:
        case = expected["case"]
        if case not in reports:
            reports[case] = DiffReport.model_validate_json(
                (output / f"{label}-{case}-cold.json").read_text())
        items = reports[case].items
        location = {key: expected[key] for key in ("page", "bbox", "min_region_coverage") if key in expected}
        content = [i for i in items if i.review_lane == ReviewLane.CONTENT and _matches(i, location)]
        visuals = [i for i in items if i.review_lane == ReviewLane.NEEDS_VISUAL_REVIEW and _matches(i, location)]
        if expected["kind"] == "content":
            matches = [i for i in content if _matches(i.model_copy(update={
                "old_value": re.sub(r"\s+", "", i.old_value or ""),
                "new_value": re.sub(r"\s+", "", i.new_value or ""),
            }), expected)]
            status = ("passed" if matches else "incorrect_content" if content
                      else "visual_only" if visuals else "missing")
        elif expected["kind"] == "no_content_claim":
            matches = []
            status = "false_content_claim" if content else "passed"
        elif expected["kind"] == "max_content_items":
            matches = []
            status = "duplicate_content" if len(content) > expected["max_items"] else "passed"
        else:
            raise ValueError(f"Unknown content-truth kind: {expected['kind']}")
        checks.append({"case": case, "id": expected["id"], "kind": expected["kind"],
                       "status": status, "passed": status == "passed", "note": expected.get("note"),
                       "matched_ids": [i.id for i in matches],
                       "located_content": [{"id": i.id, "type": i.diff_type.value,
                                            "old": i.old_value, "new": i.new_value} for i in content],
                       "visual_ids": [i.id for i in visuals]})
    return {"truth_path": truth_path, "scope": truth["scope"],
            "truth_sha256": hashlib.sha256((root / truth_path).read_bytes()).hexdigest(),
            "passed": all(row["passed"] for row in checks),
            "status_counts": dict(Counter(row["status"] for row in checks)), "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--manifest", default="benchmarks/golden/v2/manifest.json")
    parser.add_argument("--forward-label", default="forward")
    parser.add_argument("--truth", default="benchmarks/golden/v2/content_truth.json")
    parser.add_argument("--audit-only", action="store_true", help="Re-evaluate saved results without rerunning OCR")
    args = parser.parse_args()
    root, output = args.repo_root, args.results_dir
    output.mkdir(parents=True, exist_ok=True)
    from config import settings
    if (not settings.data_dir.resolve().is_relative_to(output.resolve())
            or settings.data_dir.resolve() in {root.resolve() / "runtime", Path("/app/runtime")}):
        raise SystemExit("Set DATA_DIR to an isolated directory inside --results-dir; production caches must not be cleared")
    manifest = json.loads((root / args.manifest).read_text())
    forward = json.loads((output / f"{args.forward_label}.json").read_text())
    for name, expected_hash in forward["source_sha256"].items():
        if hashlib.sha256((BACKEND / name).read_bytes()).hexdigest() != expected_hash:
            raise SystemExit("Forward benchmark source differs from current engine; rerun the forward benchmark")
    result = {
        "runtime": runtime_model_manifest(),
        "source_sha256": {str(path.relative_to(BACKEND)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (BACKEND / 'services').glob('*.py')},
        "revision": source_revision(root),
        "scope": "local real-PDF regression; anchor coverage is distinct from OCR correctness",
        "inventory": [], "self_comparisons": [], "cases": [],
    }
    def save():
        (output / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if args.audit_only:
        existing = json.loads((output / "verification.json").read_text())
        if existing["source_sha256"] != result["source_sha256"]:
            raise SystemExit("Engine source changed; rerun verification instead of reusing old reports")
        existing["content_truth"] = evaluate_content_truth(root, output, args.forward_label, args.truth)
        (output / "verification.json").write_text(json.dumps(existing, ensure_ascii=False, indent=2))
        print(json.dumps(existing["content_truth"], ensure_ascii=False, indent=2))
        if not existing["content_truth"]["passed"]:
            raise SystemExit(1)
        return
    for case in manifest["cases"]:
        old, new = (root / case[key] for key in ("old_pdf", "new_pdf"))
        for side, pdf in (("old", old), ("new", new)):
            with fitz.open(pdf) as doc:
                result["inventory"].append({
                    "case": case["id"], "side": side, "path": str(pdf.relative_to(root)),
                    "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "pages": len(doc),
                    "text_characters": sum(len(p.get_text().strip()) for p in doc),
                })
            clear_parse_cache()
            clear_pixel_diff_cache(include_disk=True)
            parsed = parse_pdf(str(pdf))
            start = time.perf_counter()
            report = generate_diff_report("acceptance-self", pdf.name, pdf.name, parsed, parsed,
                                          str(pdf), str(pdf), include_enrichment=True)
            row = {"case": case["id"], "side": side, "seconds": round(time.perf_counter()-start, 4),
                   "total_diffs": report.total_diffs, "warnings": report.engine_warnings,
                   "passed": report.total_diffs == 0 and not report.engine_warnings}
            result["self_comparisons"].append(row)
            print(json.dumps({"self": row}, ensure_ascii=False), flush=True)
            save()
        cold = DiffReport.model_validate_json((output / f"{args.forward_label}-{case['id']}-cold.json").read_text())
        warm = DiffReport.model_validate_json((output / f"{args.forward_label}-{case['id']}-warm.json").read_text())
        anchors = []
        for expected in case.get("must_detect", []):
            hits = [item for item in cold.items if _matches(item, expected)]
            anchors.append({"id": expected["id"], "status": (
                "content_candidate" if any(i.review_lane == ReviewLane.CONTENT for i in hits)
                else "visual_only" if hits else "missing"),
                "hits": [i.id for i in hits]})
        clear_parse_cache()
        clear_pixel_diff_cache(include_disk=True)
        new_doc, old_doc = parse_pdf(str(new)), parse_pdf(str(old))
        start = time.perf_counter()
        reverse = generate_diff_report("acceptance-reverse", new.name, old.name, new_doc, old_doc,
                                       str(new), str(old), include_enrichment=True)
        elapsed = time.perf_counter()-start
        (output / f"reverse-{case['id']}.json").write_text(reverse.model_dump_json(indent=2))
        forward_sig, reverse_sig = content_signature(cold), content_signature(reverse, reverse=True)
        row = {"case": case["id"], "anchors": anchors,
               "cache_content_consistent": forward_sig == content_signature(warm),
               "cache_items_consistent": [i.model_dump() for i in cold.items] == [i.model_dump() for i in warm.items],
               "content_candidates": sum(i.review_lane == ReviewLane.CONTENT for i in cold.items),
               "visual_only": cold.unresolved_region_count,
               "reverse_seconds": round(elapsed, 4), "reverse_total": reverse.total_diffs,
               "reverse_content_mirrors_forward": forward_sig == reverse_sig,
               "forward_only_claims": describe_signatures(forward_sig - reverse_sig),
               "reverse_only_claims": describe_signatures(reverse_sig - forward_sig),
               "reverse_warnings": reverse.engine_warnings}
        result["cases"].append(row)
        print(json.dumps({"case": row}, ensure_ascii=False), flush=True)
        save()
    result["summary"] = {
        "files": len(result["inventory"]), "pages": sum(i["pages"] for i in result["inventory"]),
        "self_passed": sum(i["passed"] for i in result["self_comparisons"]),
        "cache_items_consistent_cases": sum(i["cache_items_consistent"] for i in result["cases"]),
        "reverse_content_consistent_cases": sum(i["reverse_content_mirrors_forward"] for i in result["cases"]),
        "anchor_status": dict(Counter(a["status"] for c in result["cases"] for a in c["anchors"])),
        "content_candidates": sum(i["content_candidates"] for i in result["cases"]),
        "visual_only": sum(i["visual_only"] for i in result["cases"]),
    }
    result["content_truth"] = evaluate_content_truth(root, output, args.forward_label, args.truth)
    save()
    print(json.dumps(result["summary"], ensure_ascii=False), flush=True)
    # Reverse differences are reported for manual review; they are not proof of
    # which direction is correct. Zero-change and cache consistency are strict.
    if not all(i["passed"] for i in result["self_comparisons"]) or not all(
            i["cache_items_consistent"] for i in result["cases"]) or not result["content_truth"]["passed"]:
        raise SystemExit("Acceptance failed; inspect verification.json including content_truth")


if __name__ == "__main__":
    main()
