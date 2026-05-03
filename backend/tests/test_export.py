import json
from csv import DictReader
from pathlib import Path

from models.diff_models import BBox, CheckStatus, ChecklistItem, DiffItem, DiffReport, DiffType
from services.export_service import export_review_log_csv, export_review_log_json


def test_export_review_log_json_contains_diff_checklist_and_logs(tmp_path: Path):
    report = DiffReport(
        project_id="default",
        old_filename="old.pdf",
        new_filename="new.pdf",
        created_at="2026-04-12T00:00:00+00:00",
        total_diffs=1,
        summary="parser_old=docling, parser_new=docling",
        items=[
            DiffItem(
                id="d001",
                diff_type=DiffType.NUMBER_MODIFIED,
                old_value="0.216%",
                new_value="0.195%",
                old_bbox=BBox(page=1, x0=1, y0=2, x1=3, y1=4),
                new_bbox=BBox(page=1, x0=5, y0=6, x1=7, y1=8),
                context="第 1 頁 保單利率",
                confidence=0.98,
                reviewed=True,
                reviewed_by="alice",
                reviewed_at="2026-04-12T01:00:00+00:00",
            )
        ],
    )
    checklist = [
        ChecklistItem(
            item_id="C001",
            check_type="number",
            search_keyword="保單利率",
            expected_old="0.216%",
            expected_new="0.195%",
            status=CheckStatus.CONFIRMED,
            matched_diff_id="d001",
            note="verified",
        )
    ]
    review_logs = [
        {
            "id": "log-1",
            "comparison_id": "cmp-001",
            "diff_item_id": "d001",
            "action": "confirmed",
            "reviewer": "alice",
            "note": "looks good",
            "created_at": "2026-04-12T01:00:00+00:00",
        }
    ]

    exported = export_review_log_json(
        "cmp-001",
        report,
        checklist=checklist,
        review_counts={"confirmed": 1, "flagged": 0},
        review_logs=review_logs,
        output_path=str(tmp_path / "cmp-001_log.json"),
    )

    payload = json.loads(Path(exported).read_text(encoding="utf-8"))

    assert payload["comparison_id"] == "cmp-001"
    assert payload["diff_summary"]["total"] == 1
    assert payload["diff_summary"]["confirmed"] == 1
    assert payload["checklist_summary"]["confirmed"] == 1
    assert payload["diff_items"][0]["id"] == "d001"
    assert payload["checklist_items"][0]["matched_diff_id"] == "d001"
    assert payload["review_logs"][0]["action"] == "confirmed"


def test_export_review_log_csv_contains_enriched_log_rows(tmp_path: Path):
    report = DiffReport(
        project_id="default",
        old_filename="old.pdf",
        new_filename="new.pdf",
        created_at="2026-04-12T00:00:00+00:00",
        total_diffs=1,
        items=[
            DiffItem(
                id="d001",
                diff_type=DiffType.TEXT_MODIFIED,
                old_value="第一年解約費用",
                new_value="前三年解約費用",
                old_bbox=BBox(page=2, x0=1, y0=2, x1=3, y1=4),
                new_bbox=BBox(page=2, x0=5, y0=6, x1=7, y1=8),
                context="第 2 頁 解約費用",
                confidence=0.91,
                reviewed=True,
                reviewed_by="bob",
                reviewed_at="2026-04-12T02:00:00+00:00",
            )
        ],
    )
    checklist = [
        ChecklistItem(
            item_id="C002",
            check_type="text",
            search_keyword="解約費用",
            expected_old="第一年解約費用",
            expected_new="前三年解約費用",
            status=CheckStatus.ANOMALY,
            matched_diff_id="d001",
            note="manual review",
        )
    ]
    review_logs = [
        {
            "id": "log-2",
            "comparison_id": "cmp-002",
            "diff_item_id": "d001",
            "action": "flagged",
            "reviewer": "bob",
            "note": "needs legal review",
            "created_at": "2026-04-12T02:00:00+00:00",
        }
    ]

    exported = export_review_log_csv(
        "cmp-002",
        report,
        checklist=checklist,
        review_logs=review_logs,
        output_path=str(tmp_path / "cmp-002_log.csv"),
    )

    with Path(exported).open("r", encoding="utf-8-sig", newline="") as csvfile:
        rows = list(DictReader(csvfile))

    assert len(rows) == 1
    assert rows[0]["比對ID"] == "cmp-002"
    assert rows[0]["差異ID"] == "d001"
    assert rows[0]["審核動作"] == "flagged"
    assert rows[0]["對應檢核項目"] == "C002"
    assert rows[0]["目前審核人員"] == "bob"
