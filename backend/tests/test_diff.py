from models.diff_models import BBox, DiffItem, DiffType
from services.diff_service import (
    _extract_priority_ocr_text,
    _is_reliable_ocr_text,
    generate_diff_report,
    merge_diff_results,
)
from services.parser_service import ParsedDocument, ParsedParagraph


def _paragraph(text: str, page: int = 1, y0: float = 100.0, y1: float = 120.0) -> ParsedParagraph:
    return ParsedParagraph(
        text=text,
        bbox=BBox(page=page, x0=10.0, y0=y0, x1=200.0, y1=y1),
    )


def test_generate_diff_report_detects_number_change():
    old_doc = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("Monthly fee 0.216%")],
        tables=[],
        raw_json={},
    )
    new_doc = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("Monthly fee 0.195%")],
        tables=[],
        raw_json={},
    )

    report = generate_diff_report(
        project_id="p001",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_doc=old_doc,
        new_doc=new_doc,
    )

    assert report.total_diffs == 1
    assert report.items[0].diff_type == DiffType.NUMBER_MODIFIED
    assert report.items[0].id == "d001"


def test_generate_diff_report_detects_added_paragraph():
    old_doc = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("Clause A")],
        tables=[],
        raw_json={},
    )
    new_doc = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("Clause A"), _paragraph("Clause B", page=1, y0=80, y1=95)],
        tables=[],
        raw_json={},
    )

    report = generate_diff_report(
        project_id="p001",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_doc=old_doc,
        new_doc=new_doc,
    )

    assert report.total_diffs == 1
    assert report.items[0].diff_type == DiffType.ADDED


def test_merge_keeps_local_text_diff_inside_large_visual_region():
    large_region = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=2, x0=20, y0=80, x1=560, y1=760),
        new_bbox=BBox(page=2, x0=20, y0=80, x1=560, y1=760),
        context="Page 2 visual change",
        confidence=0.95,
    )
    local_text = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="old clause",
        new_value="new clause",
        old_bbox=BBox(page=2, x0=90, y0=500, x1=180, y1=518),
        new_bbox=BBox(page=2, x0=90, y0=500, x1=180, y1=518),
        context="Page 2 text change",
        confidence=0.95,
    )

    merged = merge_diff_results([local_text], [], [large_region])

    assert len(merged) == 1
    assert merged[0].diff_type == DiffType.TEXT_MODIFIED
    assert merged[0].old_value == "old clause"


def test_extracts_priority_control_no_from_noisy_footer_ocr():
    old_text = "??023.02?? Control No : 2301-2501-OP2-0043 TTT"
    new_text = "??024.07?? Control No : OP-2407-2607-0503 TTT"

    assert _extract_priority_ocr_text(old_text) == (
        "Version: 023.02; Control No: 2301-2501-OP2-0043"
    )
    assert _extract_priority_ocr_text(new_text) == (
        "Version: 024.07; Control No: OP-2407-2607-0503"
    )


def test_ocr_garbage_without_priority_pattern_is_not_reliable_text():
    garbage = "?啁鈭箏ˊ?唬?摰? ### [PAYV 選 1 說 了"

    assert not _is_reliable_ocr_text(garbage)


def test_footer_control_no_diff_survives_large_visual_dedup():
    large_region = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=2, x0=300, y0=0, x1=590, y1=90),
        new_bbox=BBox(page=2, x0=300, y0=0, x1=590, y1=90),
        context="Page 2 footer visual change",
        confidence=0.95,
    )
    footer_control = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="Version: 2023.02; Control No: 2301-2501-OP2-0043",
        new_value="Version: 2024.07; Control No: OP-2407-2607-0503",
        old_bbox=BBox(page=2, x0=445, y0=18, x1=565, y1=36),
        new_bbox=BBox(page=2, x0=445, y0=18, x1=565, y1=36),
        context="Page 2 footer control/version",
        confidence=0.98,
    )

    merged = merge_diff_results([footer_control], [], [large_region])

    assert len(merged) == 1
    assert merged[0].diff_type == DiffType.NUMBER_MODIFIED
    assert "OP-2407-2607-0503" in (merged[0].new_value or "")


def test_merge_nearby_diffs_does_not_join_distant_page_regions():
    left_change = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="A",
        new_value="B",
        old_bbox=BBox(page=2, x0=40, y0=700, x1=90, y1=718),
        new_bbox=BBox(page=2, x0=40, y0=700, x1=90, y1=718),
        context="Page 2",
        confidence=0.85,
    )
    right_change = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="C",
        new_value="D",
        old_bbox=BBox(page=2, x0=360, y0=700, x1=410, y1=718),
        new_bbox=BBox(page=2, x0=360, y0=700, x1=410, y1=718),
        context="Page 2",
        confidence=0.85,
    )

    merged = merge_diff_results([left_change, right_change], [], None)

    assert len(merged) == 2
