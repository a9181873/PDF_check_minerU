from models.diff_models import BBox, DiffItem, DiffType
from services.diff_service import (
    _drop_non_numeric_modifications,
    _extract_priority_ocr_text,
    _is_reliable_ocr_pair,
    _is_reliable_ocr_text,
    _same_native_text_is_rendering_noise,
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


def test_generate_diff_report_hides_wording_only_change():
    old_doc = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("本公司負責給付")],
        tables=[],
        raw_json={},
    )
    new_doc = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("本契約負責給付")],
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

    assert report.total_diffs == 0


def _word(x0: float, y0: float, x1: float, y1: float, text: str):
    return (x0, y0, x1, y1, text, 0, 0, 0)


def test_same_native_text_with_stable_bbox_is_rendering_noise():
    old_words = [_word(10, 20, 80, 32, "Clause")]
    new_words = [_word(10.5, 20.5, 80.5, 32.5, "Clause")]

    assert _same_native_text_is_rendering_noise(old_words, new_words)


def test_same_native_text_with_moved_bbox_is_content_position_change():
    old_words = [_word(10, 20, 80, 32, "Clause")]
    new_words = [_word(35, 20, 105, 32, "Clause")]

    assert not _same_native_text_is_rendering_noise(old_words, new_words)


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


def test_extracts_short_priority_control_no_formats():
    old_text = "《2026.02》 Control No : OP-2602-0081"
    new_text = "《2026.05》 Control No : 2605-OP-0029"

    assert _extract_priority_ocr_text(old_text) == (
        "Version: 2026.02; Control No: OP-2602-0081"
    )
    assert _extract_priority_ocr_text(new_text) == (
        "Version: 2026.05; Control No: 2605-OP-0029"
    )


def test_priority_ocr_does_not_treat_table_amount_as_version():
    table_noise = "OU | 77 109,972.00 | 975.18 | 189,576.40 | 0.00"

    assert _extract_priority_ocr_text(table_noise) is None


def test_ocr_garbage_without_priority_pattern_is_not_reliable_text():
    garbage = "### [PAYV ??1"

    assert not _is_reliable_ocr_text(garbage)


def test_ocr_pair_rejects_fragmented_garbage():
    old_text = "A\n1\nB XX )\nC"
    new_text = "X\n\nY\n[PAYV\nZ 1"

    assert not _is_reliable_ocr_pair(old_text, new_text)


def test_reliable_ocr_pair_allows_dense_numeric_table_text():
    old_text = "109,972.00 189,576.40 238,425.27 39,156.77"
    new_text = "345,414.00 346,620.00 348,618.00 321,411.00"

    assert _is_reliable_ocr_pair(old_text, new_text)


def test_reliable_ocr_pair_can_be_used_for_image_only_local_text():
    old_text = "海外突發疾病醫療相關給付金額 上限調整"
    new_text = "突發疾病醫療相關給付金額 上限調整"

    assert _is_reliable_ocr_pair(old_text, new_text)


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


def test_priority_control_diff_does_not_merge_with_nearby_text():
    footer_control = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="Version: 2026.02; Control No: OP-2602-0081",
        new_value="Version: 2026.05; Control No: 2605-OP-0029",
        old_bbox=BBox(page=6, x0=506, y0=11, x1=590, y1=40),
        new_bbox=BBox(page=6, x0=506, y0=11, x1=590, y1=40),
        context="Page 6 footer control/version",
        confidence=0.98,
    )
    nearby_text = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="old nearby footer text",
        new_value="new nearby footer text",
        old_bbox=BBox(page=6, x0=420, y0=15, x1=500, y1=35),
        new_bbox=BBox(page=6, x0=420, y0=15, x1=500, y1=35),
        context="Page 6 footer text",
        confidence=0.90,
    )

    merged = merge_diff_results([footer_control, nearby_text], [], None)

    assert len(merged) == 2
    assert any("2605-OP-0029" in (item.new_value or "") for item in merged)
    assert any(item.new_value == "new nearby footer text" for item in merged)


def test_image_only_diff_is_suppressed():
    image_only = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        context="Page 1 表格/版面變更",
        confidence=0.95,
    )
    text_change = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="舊內容",
        new_value="新內容",
        old_bbox=BBox(page=2, x0=40, y0=400, x1=200, y1=418),
        new_bbox=BBox(page=2, x0=40, y0=400, x1=200, y1=418),
        context="Page 2",
        confidence=0.9,
    )

    merged = merge_diff_results([text_change], [], [image_only])

    assert all(item.diff_type != DiffType.IMAGE_DIFF for item in merged)
    assert len(merged) == 1
    assert merged[0].diff_type == DiffType.TEXT_MODIFIED


def test_image_only_visual_fallback_can_be_retained():
    image_only = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        context="Page 1 表格/版面變更",
        confidence=0.95,
    )
    stats = {}

    merged = merge_diff_results([], [], [image_only], stats=stats, keep_image_diffs=True)

    assert len(merged) == 1
    assert merged[0].diff_type == DiffType.IMAGE_DIFF
    assert stats["retained_visual"] == 1


def test_non_numeric_filter_can_keep_image_fallback():
    image_only = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        context="Page 1 表格/版面變更",
        confidence=0.95,
    )

    assert _drop_non_numeric_modifications([image_only]) == []
    kept = _drop_non_numeric_modifications([image_only], keep_image_diffs=True)
    assert kept == [image_only]


def test_generate_diff_report_retains_visual_fallback_for_image_pdf(monkeypatch):
    image_only = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        context="Page 1 表格/版面變更",
        confidence=0.95,
    )
    old_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    new_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)

    monkeypatch.setattr("services.diff_service.diff_pixels", lambda *_args, **_kwargs: [image_only])
    monkeypatch.setattr("services.diff_service.diff_images", lambda *_args, **_kwargs: [])

    report = generate_diff_report(
        project_id="p001",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_doc=old_doc,
        new_doc=new_doc,
        old_pdf_path="/tmp/old.pdf",
        new_pdf_path="/tmp/new.pdf",
    )

    assert report.total_diffs == 1
    assert report.items[0].diff_type == DiffType.IMAGE_DIFF
    assert report.suppressed_count == 0
    assert "visual_retained=1" in (report.summary or "")


def test_overlapping_text_diffs_in_tall_cell_merge_into_one_block():
    # Two token-level diffs that share the same tall paragraph bbox (height 120
    # exceeds the 80pt merge cap) — they overlap, so they must still collapse.
    box = dict(page=1, x0=50, x1=250, y0=600, y1=720)
    first = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="甲",
        new_value="乙",
        old_bbox=BBox(**box),
        new_bbox=BBox(**box),
        context="Page 1 table cell",
        confidence=0.85,
    )
    second = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="丙",
        new_value="丁",
        old_bbox=BBox(**box),
        new_bbox=BBox(**box),
        context="Page 1 table cell",
        confidence=0.85,
    )

    merged = merge_diff_results([first, second], [], None)

    assert len(merged) == 1


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
