from models.diff_models import BBox, DiffEvidence, DiffItem, DiffReport, DiffType
from scripts.run_golden_benchmark import evaluate_preliminary_region_coverage, evaluate_report


def _report(*items: DiffItem) -> DiffReport:
    return DiffReport(
        project_id="benchmark",
        old_filename="old.pdf",
        new_filename="new.pdf",
        created_at="2026-07-19T00:00:00+00:00",
        total_diffs=len(items),
        items=list(items),
    )


def _number_item(item_id: str, old_value: str, new_value: str) -> DiffItem:
    return DiffItem(
        id=item_id,
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value=old_value,
        new_value=new_value,
        old_bbox=BBox(page=1, x0=10, y0=10, x1=30, y1=30),
        new_bbox=BBox(page=1, x0=10, y0=10, x1=30, y1=30),
        context="Page 1 圖片數字變更",
        confidence=0.95,
    )


def test_evaluate_report_uses_one_item_for_only_one_expected_region():
    report = _report(_number_item("d001", "24", "28"))
    case = {
        "must_detect": [
            {"id": "first", "page": 1},
            {"id": "second", "page": 1},
        ]
    }

    evaluation = evaluate_report(report, case)

    assert evaluation["must_detect_passed"] == 1
    assert evaluation["must_detect_recall"] == 0.5


def test_evaluate_report_uses_maximum_matching_for_broad_and_narrow_expectations():
    broad_item = _number_item("d001", "24", "28")
    narrow_item = _number_item("d002", "50", "60")
    report = _report(broad_item, narrow_item)
    case = {
        "must_detect": [
            {"id": "broad", "page": 1},
            {"id": "narrow", "page": 1, "old_regex": "^24$"},
        ]
    }

    evaluation = evaluate_report(report, case)

    assert evaluation["must_detect_recall"] == 1.0
    assert [row["matched_item_id"] for row in evaluation["must_detect"]] == ["d002", "d001"]


def test_evaluate_report_flags_forbidden_numeric_interpretation():
    report = _report(_number_item("d001", "95", "00"))
    case = {
        "must_not_interpret": [
            {
                "id": "partial_percentage",
                "page": 1,
                "diff_types": ["number_modified"],
                "old_regex": "^95$",
                "new_regex": "^00$",
            }
        ]
    }

    evaluation = evaluate_report(report, case)

    assert evaluation["numeric_interpretation_false_positives"] == 1
    assert evaluation["prohibited_interpretations"][0]["hits"] == ["d001"]


def test_evaluate_report_checks_forbidden_values_inside_evidence():
    item = _number_item("d001", "", "")
    item.diff_type = DiffType.IMAGE_DIFF
    item.evidence = [
        DiffEvidence(
            source="tesseract_local_ocr",
            kind="number_modified",
            old_value="95",
            new_value="00",
            old_bbox=item.old_bbox,
            new_bbox=item.new_bbox,
            confidence=0.5,
        )
    ]
    case = {
        "must_not_interpret": [
            {
                "id": "partial_percentage",
                "page": 1,
                "diff_types": ["number_modified"],
                "old_regex": "^95$",
                "new_regex": "^00$",
            }
        ]
    }

    assert evaluate_report(_report(item), case)["numeric_interpretation_false_positives"] == 1


def test_evaluate_report_supports_expected_region_coverage():
    report = _report(_number_item("d001", "24", "28"))
    case = {
        "must_detect": [
            {
                "id": "inside",
                "page": 1,
                "bbox": {"page": 1, "x0": 15, "y0": 15, "x1": 25, "y1": 25},
                "min_region_coverage": 1.0,
            }
        ]
    }

    assert evaluate_report(report, case)["must_detect_recall"] == 1.0


def test_preliminary_region_coverage_requires_distinct_items_and_bbox_overlap():
    report = _report(_number_item("d001", "24", "28"))
    case = {
        "must_detect": [
            {
                "id": "inside",
                "page": 1,
                "bbox": {"page": 1, "x0": 15, "y0": 15, "x1": 25, "y1": 25},
                "min_region_coverage": 1.0,
            },
            {"id": "second", "page": 1},
        ]
    }

    evaluation = evaluate_preliminary_region_coverage(report, case)

    assert evaluation["passed"] == 1
    assert evaluation["region_recall"] == 0.5
