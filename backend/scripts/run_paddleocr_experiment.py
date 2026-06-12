from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings
from services.diff_service import generate_diff_report
from services.parser_service import _parse_via_fitz


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the optional local PaddleOCR A/B metadata path on two PDFs.")
    parser.add_argument("old_pdf", type=Path)
    parser.add_argument("new_pdf", type=Path)
    parser.add_argument("--lang", default=settings.paddle_ocr_lang)
    parser.add_argument("--dpi", type=int, default=settings.paddle_ocr_dpi)
    parser.add_argument("--max-pages", type=int, default=settings.paddle_ocr_max_pages)
    parser.add_argument("--min-confidence", type=float, default=settings.paddle_ocr_min_confidence)
    parser.add_argument(
        "--force-image-mode",
        action="store_true",
        help="Force the image-PDF path even if the PDFs contain a native text layer.",
    )
    args = parser.parse_args()

    settings.enable_paddle_ocr_experiment = True
    settings.paddle_ocr_lang = args.lang
    settings.paddle_ocr_dpi = args.dpi
    settings.paddle_ocr_max_pages = args.max_pages
    settings.paddle_ocr_min_confidence = args.min_confidence

    old_doc = _parse_via_fitz(args.old_pdf)
    new_doc = _parse_via_fitz(args.new_pdf)
    if args.force_image_mode:
        old_doc.is_image_pdf = True
        new_doc.is_image_pdf = True

    started = time.perf_counter()
    report = generate_diff_report(
        project_id="paddleocr_experiment",
        old_filename=args.old_pdf.name,
        new_filename=args.new_pdf.name,
        old_doc=old_doc,
        new_doc=new_doc,
        old_pdf_path=str(args.old_pdf),
        new_pdf_path=str(args.new_pdf),
    )
    elapsed = time.perf_counter() - started

    print(
        json.dumps(
            {
                "elapsed_seconds": round(elapsed, 3),
                "summary": report.summary,
                "total_diffs": report.total_diffs,
                "engine_warnings": report.engine_warnings,
                "paddle_ocr": report.engine_stats.get("paddle_ocr"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
