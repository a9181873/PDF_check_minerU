#!/usr/bin/env python3
"""Compare golden benchmark JSON files from Mac, OCI, or onsite hosts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    loaded = [json.loads(path.read_text(encoding="utf-8")) for path in args.results]
    lines = [
        "# PDF/OCR 跨主機效能比較",
        "",
        "| 主機 | 模式 | CPU/RAM | 初步 P95 | 完整 P95 | 必抓召回 | 禁止誤報 | 峰值 RAM | SLA |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for result in loaded:
        hardware = result["hardware"]
        resources = f"{hardware.get('logical_cores') or hardware.get('cpu_count')} threads / {hardware.get('memory_total_gb')}GB"
        for mode, block in result["modes"].items():
            summary = block["summary"]
            sla = summary["sla"]
            passed = all(sla.values()) and summary["prohibited_false_positives"] == 0
            lines.append(
                f"| {hardware['host_label']} | {mode} | {resources} | "
                f"{summary['initial_ready_p95_seconds']:.2f}s | {summary['complete_p95_seconds']:.2f}s | "
                f"{summary['must_detect_recall']:.1%} | {summary['prohibited_false_positives']} | "
                f"{summary['peak_memory_mb']:.1f}MB | {'通過' if passed else '未通過'} |"
            )

    lines.extend(
        [
            "",
            "## 判讀規則",
            "",
            "- 初步 P95 必須不超過 15 秒，完整 P95 必須不超過 90 秒。",
            "- 任一已知必抓差異漏失或禁止誤報出現，即判定該設定不合格。",
            "- 六對資料只適合作為既有案例回歸，不作母體準確率推論。",
            "",
        ]
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
