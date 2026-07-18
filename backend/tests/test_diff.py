import threading

from models.diff_models import BBox, DiffEvidence, DiffItem, DiffType
from config import settings
from services import diff_service
from services.diff_service import (
    _compact_numeric_ocr_pair,
    _coalesce_reviewable_visual_items,
    _drop_non_numeric_modifications,
    _extract_priority_ocr_text,
    _full_page_image_placement_count,
    _is_reliable_image_pdf_text_diff,
    _is_reliable_ocr_pair,
    _is_reliable_ocr_text,
    _labeled_component_geometry,
    _numeric_ocr_confusion_count,
    _ocr_rendered_page_pair,
    _same_native_text_is_rendering_noise,
    clear_pixel_diff_cache,
    diff_aligned_paragraphs,
    diff_pixels,
    generate_diff_report,
    merge_diff_results,
)
from services.parser_service import ParsedDocument, ParsedParagraph


def _paragraph(text: str, page: int = 1, y0: float = 100.0, y1: float = 120.0) -> ParsedParagraph:
    return ParsedParagraph(
        text=text,
        bbox=BBox(page=page, x0=10.0, y0=y0, x1=200.0, y1=y1),
    )


def test_labeled_component_geometry_matches_legacy_full_mask_scan():
    import numpy as np
    from scipy import ndimage

    changed = np.zeros((18, 24), dtype=bool)
    changed[1:4, 2:5] = True
    changed[8:10, 12:15] = True
    changed[14:17, 19:22] = True
    labeled, count = ndimage.label(ndimage.binary_dilation(changed, iterations=1))

    legacy = []
    for region_id in range(1, count + 1):
        region = labeled == region_id
        rows, columns = np.where(region)
        legacy.append(
            (
                region_id,
                int(rows.min()),
                int(rows.max()) + 1,
                int(columns.min()),
                int(columns.max()) + 1,
                int((changed & region).sum()),
                int(region.sum()),
            )
        )

    assert _labeled_component_geometry(labeled, changed, count) == legacy


def test_full_page_image_prefilter_only_skips_pages_without_smaller_placements():
    class Rect:
        width = 100.0
        height = 200.0

    class Page:
        rect = Rect()

        def __init__(self, placements):
            self._placements = placements

        def get_image_info(self, **_kwargs):
            return self._placements

    full_page = {"bbox": (0.0, 0.0, 100.0, 200.0)}
    small_overlay = {"bbox": (10.0, 10.0, 30.0, 30.0)}

    assert _full_page_image_placement_count(Page([full_page])) == 1
    assert _full_page_image_placement_count(Page([full_page, full_page])) == 2
    assert _full_page_image_placement_count(Page([full_page, small_overlay])) == 0
    assert _full_page_image_placement_count(Page([])) == 0


def test_ocr_page_pair_renders_on_caller_thread_before_parallel_ocr(monkeypatch):
    caller_thread = threading.get_ident()
    render_threads = []

    class Pixmap:
        def __init__(self, name):
            self.name = name

        @property
        def width(self):
            assert threading.get_ident() == caller_thread
            return 1

        @property
        def height(self):
            assert threading.get_ident() == caller_thread
            return 1

        @property
        def samples(self):
            assert threading.get_ident() == caller_thread
            return self.name.encode()

    class Page:
        def __init__(self, name):
            self.name = name

        def get_pixmap(self, **_kwargs):
            render_threads.append(threading.get_ident())
            return Pixmap(self.name)

    monkeypatch.setattr(
        diff_service,
        "_ocr_raster_payload",
        lambda payload, **_kwargs: f"ocr:{payload[2].decode()}",
    )

    def run_pair(function, old_input, new_input):
        from concurrent.futures import ThreadPoolExecutor

        assert render_threads == [caller_thread, caller_thread]
        with ThreadPoolExecutor(max_workers=1) as pool:
            old_future = pool.submit(function, old_input)
            new_result = function(new_input)
            return old_future.result(), new_result

    assert _ocr_rendered_page_pair(
        Page("old"),
        Page("new"),
        object(),
        zoom=4.0,
        lang="chi_tra+eng",
        psm="6",
        run_pair=run_pair,
    ) == ("ocr:old", "ocr:new")


def test_pixel_diff_cache_reuses_result_and_restores_metadata(monkeypatch):
    clear_pixel_diff_cache()
    calls = 0

    def fake_uncached(*_args, engine_stats=None, engine_warnings=None, **_kwargs):
        nonlocal calls
        calls += 1
        engine_stats["pixel_ocr_calls_total"] = 4
        engine_warnings.append("pixel: test warning")
        return [
            DiffItem(
                id="",
                diff_type=DiffType.IMAGE_DIFF,
                old_bbox=BBox(page=1, x0=1, y0=1, x1=2, y1=2),
                new_bbox=BBox(page=1, x0=1, y0=1, x1=2, y1=2),
                context="Page 1 表格/版面變更",
                confidence=0.95,
            )
        ]

    monkeypatch.setattr(settings, "enable_pixel_diff_cache", True)
    monkeypatch.setattr(settings, "pixel_diff_cache_max_entries", 2)
    monkeypatch.setattr(settings, "enable_persistent_analysis_cache", False)
    monkeypatch.setattr(diff_service, "_pixel_cache_key", lambda *_args: "same-pair")
    monkeypatch.setattr(diff_service, "_diff_pixels_uncached", fake_uncached)

    first_stats, first_warnings = {}, []
    first = diff_pixels("old.pdf", "new.pdf", engine_stats=first_stats, engine_warnings=first_warnings)
    first[0].id = "mutated"
    second_stats, second_warnings = {}, []
    second = diff_pixels("old.pdf", "new.pdf", engine_stats=second_stats, engine_warnings=second_warnings)

    assert calls == 1
    assert first_stats["pixel_cache_hit"] is False
    assert second_stats["pixel_cache_hit"] is True
    assert second_stats["pixel_ocr_calls_total"] == 4
    assert second_warnings == ["pixel: test warning"]
    assert second[0].id == ""
    clear_pixel_diff_cache()


def test_pixel_diff_cache_survives_process_memory_clear(monkeypatch, tmp_path):
    clear_pixel_diff_cache()
    calls = 0
    old_pdf = tmp_path / "old.pdf"
    new_pdf = tmp_path / "new.pdf"
    old_pdf.write_bytes(b"old")
    new_pdf.write_bytes(b"new")

    def fake_uncached(*_args, engine_stats=None, engine_warnings=None, **_kwargs):
        nonlocal calls
        calls += 1
        engine_stats["pixel_raw_regions"] = 1
        return [
            DiffItem(
                id="",
                diff_type=DiffType.IMAGE_DIFF,
                old_bbox=BBox(page=1, x0=1, y0=1, x1=50, y1=50),
                new_bbox=BBox(page=1, x0=1, y0=1, x1=50, y1=50),
                context="Page 1 表格/版面變更",
                confidence=0.9,
            )
        ]

    monkeypatch.setattr(settings, "enable_pixel_diff_cache", True)
    monkeypatch.setattr(settings, "enable_persistent_analysis_cache", True)
    monkeypatch.setattr(settings, "analysis_cache_dir", tmp_path / "cache")
    monkeypatch.setattr(diff_service, "_diff_pixels_uncached", fake_uncached)

    first_stats = {}
    diff_pixels(str(old_pdf), str(new_pdf), engine_stats=first_stats, engine_warnings=[])
    clear_pixel_diff_cache()
    second_stats = {}
    second = diff_pixels(str(old_pdf), str(new_pdf), engine_stats=second_stats, engine_warnings=[])

    assert calls == 1
    assert first_stats["pixel_cache_tier"] == "miss"
    assert second_stats["pixel_cache_tier"] == "disk"
    assert len(second) == 1
    clear_pixel_diff_cache(include_disk=True)


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


def test_generate_diff_report_records_engine_warnings_for_unreadable_pdf_paths():
    old_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    new_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)

    report = generate_diff_report(
        project_id="p001",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_doc=old_doc,
        new_doc=new_doc,
        old_pdf_path="/tmp/does-not-exist-old.pdf",
        new_pdf_path="/tmp/does-not-exist-new.pdf",
    )

    assert report.total_diffs == 0
    assert report.engine_stats["mode"] == "image_pdf"
    assert any(warning.startswith("pixel_error:") for warning in report.engine_warnings)
    assert any(warning.startswith("image_error:") for warning in report.engine_warnings)


def test_paddle_ocr_experiment_records_numeric_candidates(monkeypatch):
    old_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    new_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    old_paddle = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("宣告利率 0.216%")],
        tables=[],
        raw_json={},
        is_image_pdf=True,
    )
    new_paddle = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("宣告利率 0.195%")],
        tables=[],
        raw_json={},
        is_image_pdf=True,
    )
    calls = iter([old_paddle, new_paddle])

    monkeypatch.setattr("config.settings.enable_paddle_ocr_experiment", True)
    monkeypatch.setattr("services.diff_service.diff_pixels", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("services.diff_service.diff_images", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        "services.paddle_ocr_adapter.parse_image_pdf_via_paddleocr",
        lambda *_args, **_kwargs: next(calls),
    )

    report = generate_diff_report(
        project_id="p001",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_doc=old_doc,
        new_doc=new_doc,
        old_pdf_path="/tmp/old.pdf",
        new_pdf_path="/tmp/new.pdf",
    )

    paddle_stats = report.engine_stats["paddle_ocr"]
    assert paddle_stats["enabled"] is True
    assert paddle_stats["candidate_diff_count"] == 1
    assert paddle_stats["unconfirmed_changed_numeric_tokens"] == ["0.195%", "0.216%"]
    assert any(warning.startswith("paddle_ocr: detected 2 numeric tokens") for warning in report.engine_warnings)


def test_aligned_recall_ignores_section_heading_glued_to_list_marker():
    old = [
        _paragraph("8 注意事項", page=4, y0=584.0, y1=650.0),
        _paragraph("1.消費者投保前應審慎瞭解本商品之承保範圍。", page=4, y0=546.0, y1=561.0),
    ]
    new = [
        _paragraph("1.消費者投保前應審慎瞭解本商品之承保範圍。", page=4, y0=546.0, y1=561.0),
    ]

    assert diff_aligned_paragraphs(old, new) == []


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


def test_generate_diff_report_detects_wording_change():
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

    assert report.total_diffs == 1
    assert report.items[0].diff_type == DiffType.TEXT_MODIFIED


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


def test_image_only_region_is_surfaced_as_item():
    # A visual-only region that no content item explains must be KEPT as a located,
    # crop-backed item (zero-miss): hiding it behind a "N changes, go look" count is
    # the failure mode we removed. Here the image region (p1) and the text change (p2)
    # do not overlap, so both survive.
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

    merged = merge_diff_results([text_change], [], [image_only], keep_image_diffs=True)

    assert len(merged) == 2
    assert any(item.diff_type == DiffType.IMAGE_DIFF for item in merged)
    assert any(item.diff_type == DiffType.TEXT_MODIFIED for item in merged)


def test_coarse_visual_region_fuses_with_text_explanation_when_retained():
    # In image-only mode the visual region is the reviewer-facing location. OCR
    # text explains the region, but should not shrink the crop down to a tiny bbox.
    coarse_visual = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=2, x0=20, y0=380, x1=560, y1=440),
        new_bbox=BBox(page=2, x0=20, y0=380, x1=560, y1=440),
        context="Page 2 表格/版面變更",
        confidence=0.95,
    )
    text_change = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="3.90%",
        new_value="4.00%",
        old_bbox=BBox(page=2, x0=40, y0=400, x1=200, y1=418),
        new_bbox=BBox(page=2, x0=40, y0=400, x1=200, y1=418),
        context="Page 2 OCR rate",
        confidence=0.9,
    )
    stats = {}

    merged = merge_diff_results([text_change], [], [coarse_visual], stats=stats, keep_image_diffs=True)

    assert len(merged) == 1
    assert merged[0].diff_type == DiffType.NUMBER_MODIFIED
    assert merged[0].old_value == "3.90%"
    assert merged[0].new_value == "4.00%"
    assert merged[0].old_bbox == coarse_visual.old_bbox
    assert "OCR rate" in merged[0].context
    assert stats["fused_visual"] == 1


def test_non_numeric_visual_fusion_keeps_visual_fallback_type():
    coarse_visual = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=2, x0=20, y0=380, x1=560, y1=440),
        new_bbox=BBox(page=2, x0=20, y0=380, x1=560, y1=440),
        context="Page 2 表格/版面變更",
        confidence=0.95,
    )
    wording = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="舊條款",
        new_value="新條款",
        old_bbox=BBox(page=2, x0=40, y0=400, x1=200, y1=418),
        new_bbox=BBox(page=2, x0=40, y0=400, x1=200, y1=418),
        context="Page 2 OCR clause",
        confidence=0.9,
    )

    merged = merge_diff_results([wording], [], [coarse_visual], keep_image_diffs=True)

    assert len(merged) == 1
    assert merged[0].diff_type == DiffType.IMAGE_DIFF
    assert merged[0].old_value == "舊條款"
    assert merged[0].new_value == "新條款"


def test_visual_fusion_prefers_tighter_region_for_same_text():
    broad_visual = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=2, x0=0, y0=300, x1=600, y1=500),
        new_bbox=BBox(page=2, x0=0, y0=300, x1=600, y1=500),
        context="Page 2 broad visual",
        confidence=0.8,
    )
    tight_visual = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=2, x0=30, y0=390, x1=250, y1=430),
        new_bbox=BBox(page=2, x0=30, y0=390, x1=250, y1=430),
        context="Page 2 table row visual",
        confidence=0.95,
    )
    rate = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="3.90%",
        new_value="4.00%",
        old_bbox=BBox(page=2, x0=40, y0=400, x1=200, y1=418),
        new_bbox=BBox(page=2, x0=40, y0=400, x1=200, y1=418),
        context="Page 2 OCR rate",
        confidence=0.9,
    )

    merged = merge_diff_results([rate], [], [broad_visual, tight_visual], keep_image_diffs=True)

    assert len(merged) == 1
    assert merged[0].diff_type == DiffType.NUMBER_MODIFIED
    assert merged[0].old_bbox == tight_visual.old_bbox
    assert "table row visual" in merged[0].context


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


def test_content_filter_keeps_reviewable_table_visual_fallback():
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

    assert _drop_non_numeric_modifications([image_only]) == [image_only]
    kept = _drop_non_numeric_modifications([image_only], keep_image_diffs=True)
    assert kept == [image_only]


def test_content_filter_suppresses_small_visual_noise_even_in_image_mode():
    small_noise = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=20, y0=80, x1=45, y1=100),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=45, y1=100),
        context="Page 1 圖形差異 (128 px)",
        confidence=0.95,
    )
    stats = {}

    assert _drop_non_numeric_modifications(
        [small_noise],
        keep_image_diffs=True,
        stats=stats,
    ) == []
    assert stats["suppressed_non_material_visual"] == 1


def test_coalesce_reviewable_visual_items_groups_same_page_regions():
    first = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=20, y0=80, x1=250, y1=220),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=250, y1=220),
        context="Page 1 表格/版面變更",
        confidence=0.90,
    )
    second = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=260, y0=200, x1=560, y1=420),
        new_bbox=BBox(page=1, x0=260, y0=200, x1=560, y1=420),
        context="Page 1 表格/版面變更",
        confidence=0.95,
    )
    footer = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="Version: 2024.10",
        new_value="Version: 2025.10",
        old_bbox=BBox(page=1, x0=450, y0=10, x1=560, y1=40),
        new_bbox=BBox(page=1, x0=450, y0=10, x1=560, y1=40),
        context="Page 1 footer control/version",
        confidence=0.98,
    )
    stats = {}

    merged = _coalesce_reviewable_visual_items([first, second, footer], stats=stats)

    visual_items = [item for item in merged if item.diff_type == DiffType.IMAGE_DIFF]
    assert len(visual_items) == 1
    assert visual_items[0].new_bbox == BBox(page=1, x0=20, y0=80, x1=560, y1=420)
    assert "2 區域" in visual_items[0].context
    assert any(item.diff_type == DiffType.NUMBER_MODIFIED for item in merged)
    assert stats["coalesced_visual_regions"] == 1


def test_content_filter_can_keep_explained_image_fallback():
    explained = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value="舊文字",
        new_value="新文字",
        old_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=760),
        context="Page 1 表格/版面變更; OCR/text: Page 1 內容變更",
        confidence=0.95,
    )

    assert _drop_non_numeric_modifications([explained], keep_image_diffs=True) == [explained]


def test_image_pdf_text_gate_suppresses_single_glyph_ocr_drift():
    noise = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="之經濟弱勢或特定身分者",
        new_value="之經濟駱勢或特是身分者",
        old_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=100),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=560, y1=100),
        context="Page 1 內容變更",
        confidence=0.95,
    )
    stats = {}

    assert _drop_non_numeric_modifications([noise], image_pdf_text_gate=True, stats=stats) == []
    assert stats["suppressed_ocr_text"] == 1


def test_image_pdf_text_gate_keeps_title_phrase_change_together():
    title = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="台灣人壽新扶愛微型傷害保險",
        new_value="台灣人壽新扶愛微型癌症保險",
        old_bbox=BBox(page=1, x0=80, y0=640, x1=520, y1=700),
        new_bbox=BBox(page=1, x0=80, y0=640, x1=520, y1=700),
        context="Page 1 內容變更",
        confidence=0.95,
    )

    assert _drop_non_numeric_modifications([title], image_pdf_text_gate=True) == [title]


def test_image_pdf_text_gate_keeps_title_phrase_addition():
    title = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="台灣人壽新扶愛微型傷害保險",
        new_value="台灣人壽新扶愛微型傷害保險甲型",
        old_bbox=BBox(page=1, x0=80, y0=640, x1=520, y1=700),
        new_bbox=BBox(page=1, x0=80, y0=640, x1=540, y1=700),
        context="Page 1 內容變更",
        confidence=0.95,
    )

    assert _drop_non_numeric_modifications([title], image_pdf_text_gate=True) == [title]


def test_image_pdf_text_gate_suppresses_long_high_similarity_ocr_replacement():
    noise = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value=(
            "因遭受意外傷害事故，自意外傷害事故發生之日起180日以內死亡者，"
            "其身故保險金變更為喪葬費用保險金。"
        ),
        new_value=(
            "因遭受意外傷害事故，自意外傷害事故發生之日起180日以內死亡者，"
            "其身故保險金變更為卅基費用保險金。"
        ),
        old_bbox=BBox(page=2, x0=220, y0=280, x1=440, y1=380),
        new_bbox=BBox(page=2, x0=220, y0=280, x1=440, y1=380),
        context="Page 2 內容變更",
        confidence=0.95,
    )

    assert _drop_non_numeric_modifications([noise], image_pdf_text_gate=True) == []


def test_image_pdf_text_gate_suppresses_isolated_single_digit_ocr_drift():
    noise = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="7 自權閣呈說明\n情境範例說明",
        new_value="了\n情境範例說明",
        old_bbox=BBox(page=2, x0=40, y0=760, x1=200, y1=805),
        new_bbox=BBox(page=2, x0=40, y0=760, x1=200, y1=805),
        context="Page 2 內容變更",
        confidence=0.95,
    )

    assert _drop_non_numeric_modifications([noise], image_pdf_text_gate=True) == []


def test_image_pdf_text_gate_keeps_strong_numeric_ocr_change():
    item = DiffItem(
        id="",
        diff_type=DiffType.TEXT_MODIFIED,
        old_value="保險金額50萬元",
        new_value="保險金額100萬元",
        old_bbox=BBox(page=2, x0=40, y0=760, x1=200, y1=805),
        new_bbox=BBox(page=2, x0=40, y0=760, x1=200, y1=805),
        context="Page 2 內容變更",
        confidence=0.95,
    )

    assert _drop_non_numeric_modifications([item], image_pdf_text_gate=True) == [item]


def test_image_pdf_text_gate_suppresses_long_noisy_numeric_ocr():
    item = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value=(
            "註1: 上表與累計增加保險金額之相關數值為假設每年宣告利率3.90%"
            "下計算，且為人工試算容有四捨五入之誤差，實際金額以系統計算為主。"
        ),
        new_value=(
            "註1:上上表與累計增加保險金額之相關數信旋假設每年宮告利率3.9036。"
            "註9:林站只說部分保章生度有本本保險多議于能之身歷完全人能饋失人。"
        ),
        old_bbox=BBox(page=3, x0=40, y0=80, x1=560, y1=160),
        new_bbox=BBox(page=3, x0=40, y0=80, x1=560, y1=160),
        context="Page 3 內容變更",
        confidence=0.95,
    )
    stats = {}

    assert _drop_non_numeric_modifications([item], image_pdf_text_gate=True, stats=stats) == []
    assert stats["suppressed_ocr_text"] == 1


def test_image_pdf_text_gate_suppresses_number_diff_when_numbers_do_not_change():
    item = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="(本保險為非保證續保之保險商品。\n(免費申訴電話 :0800-213-269。",
        new_value="(本保險為非保證續保之保險商品。)\n(免費申訴電話 : 0800-213-269。)",
        old_bbox=BBox(page=1, x0=40, y0=720, x1=260, y1=780),
        new_bbox=BBox(page=1, x0=40, y0=720, x1=260, y1=780),
        context="Page 1 圖片數字變更",
        confidence=0.95,
    )
    stats = {}

    assert _drop_non_numeric_modifications([item], image_pdf_text_gate=True, stats=stats) == []
    assert stats["suppressed_ocr_text"] == 1


def test_image_pdf_text_gate_demotes_unreliable_number_but_keeps_visual_region():
    item = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="2",
        new_value="3",
        old_bbox=BBox(page=3, x0=40, y0=720, x1=60, y1=740),
        new_bbox=BBox(page=3, x0=40, y0=720, x1=60, y1=740),
        context="Page 3 內容變更",
        confidence=0.95,
        evidence=[
            DiffEvidence(
                source="pixel_diff",
                kind="visual_region",
                old_bbox=BBox(page=3, x0=40, y0=720, x1=60, y1=740),
                new_bbox=BBox(page=3, x0=40, y0=720, x1=60, y1=740),
                confidence=0.95,
            ),
            DiffEvidence(
                source="tesseract_local_ocr",
                kind="number_modified",
                old_value="2",
                new_value="3",
                confidence=0.95,
            ),
        ],
    )

    stats = {}
    filtered = _drop_non_numeric_modifications(
        [item],
        image_pdf_text_gate=True,
        stats=stats,
    )

    assert len(filtered) == 1
    assert filtered[0].diff_type == DiffType.IMAGE_DIFF
    assert filtered[0].old_value is None
    assert filtered[0].new_value is None
    assert filtered[0].decision_reason == "ocr_interpretation_rejected_visual_retained"
    assert [(e.source, e.kind, e.old_value, e.new_value) for e in filtered[0].evidence] == [
        ("pixel_diff", "visual_region", None, None)
    ]
    assert stats["demoted_unreliable_ocr_to_visual"] == 1


def test_nearby_pixel_ocr_merge_preserves_visual_provenance():
    items = []
    for index, x0 in enumerate((10.0, 32.0), start=1):
        bbox = BBox(page=1, x0=x0, y0=10, x1=x0 + 18, y1=30)
        items.append(
            DiffItem(
                id=f"d{index:03d}",
                diff_type=DiffType.NUMBER_MODIFIED,
                old_value=str(20 + index),
                new_value=str(30 + index),
                old_bbox=bbox,
                new_bbox=bbox,
                context="Page 1 內容變更",
                confidence=0.95,
                evidence=[
                    DiffEvidence(
                        source="pixel_diff",
                        kind="visual_region",
                        old_bbox=bbox,
                        new_bbox=bbox,
                        confidence=0.95,
                    )
                ],
            )
        )

    merged = merge_diff_results([], [], items, keep_image_diffs=True)

    assert len(merged) == 1
    assert [e.source for e in merged[0].evidence] == ["pixel_diff", "pixel_diff"]


def test_image_pdf_text_gate_keeps_number_diff_with_strong_numeric_change():
    item = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="保險金額50萬元",
        new_value="保險金額100萬元",
        old_bbox=BBox(page=2, x0=40, y0=760, x1=200, y1=805),
        new_bbox=BBox(page=2, x0=40, y0=760, x1=200, y1=805),
        context="Page 2 內容變更",
        confidence=0.95,
    )

    assert _drop_non_numeric_modifications([item], image_pdf_text_gate=True) == [item]


def test_compact_numeric_ocr_pair_recovers_small_graphic_number_change():
    assert _compact_numeric_ocr_pair("24", "28%") == ("24", "28")
    assert _compact_numeric_ocr_pair("24", "281") is None
    assert _compact_numeric_ocr_pair("244", "284") == ("244", "284")
    assert _compact_numeric_ocr_pair("2", "3") is None
    assert _compact_numeric_ocr_pair("9", "1") is None
    assert _compact_numeric_ocr_pair("7 自權閣呈說明", "了") is None


def test_compact_numeric_ocr_pair_rejects_historical_partial_ocr_values():
    for old_value, new_value in (
        ("4", "24"),
        ("35", "5"),
        ("95", "00"),
        ("64", "06"),
        ("71", "7"),
        ("99", "100"),
        ("24", "128"),
        ("100", "99"),
    ):
        assert _compact_numeric_ocr_pair(old_value, new_value) is None
        assert not _is_reliable_image_pdf_text_diff(old_value, new_value)


def test_image_pdf_numeric_gate_keeps_explicit_percentage_context():
    assert _is_reliable_image_pdf_text_diff("宣告利率 3.95%", "宣告利率 4.00%")


def test_numeric_ocr_confusion_count_detects_letters_inside_numbers():
    assert _numeric_ocr_confusion_count("給付祝壽保險金 447,6i12 美元") == 1
    assert _numeric_ocr_confusion_count("463,07 1.O00O 美元") >= 1
    assert _numeric_ocr_confusion_count("給付祝壽保險金 447,612 美元") == 0


def test_generate_diff_report_keeps_table_visual_fallback_for_image_pdf(monkeypatch):
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
    assert report.items[0].context == "Page 1 表格/版面變更"
    assert report.suppressed_count == 0
    assert "visual_retained=1" in (report.summary or "")


def test_preliminary_image_report_is_visual_first_and_reviewer_facing(monkeypatch):
    calls = []
    visual = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_bbox=BBox(page=2, x0=20, y0=80, x1=80, y1=130),
        new_bbox=BBox(page=2, x0=20, y0=80, x1=80, y1=130),
        context="Page 2 待 OCR 視覺變更",
        confidence=0.9,
    )
    old_doc = ParsedDocument(pages=2, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    new_doc = ParsedDocument(pages=2, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)

    def fake_pixels(*_args, **kwargs):
        calls.append(kwargs)
        return [visual]

    monkeypatch.setattr("services.diff_service.diff_pixels", fake_pixels)
    monkeypatch.setattr("services.diff_service.diff_images", lambda *_args, **_kwargs: [])

    report = generate_diff_report(
        project_id="p001",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_doc=old_doc,
        new_doc=new_doc,
        old_pdf_path="/tmp/old.pdf",
        new_pdf_path="/tmp/new.pdf",
        include_enrichment=False,
    )

    assert calls[0]["enable_ocr"] is False
    assert calls[0]["dpi"] == 144
    assert report.analysis_status.value == "preliminary"
    assert report.unresolved_region_count == 1
    assert report.items[0].review_lane.value == "needs_visual_review"


def test_generate_diff_report_suppresses_small_visual_noise_for_image_pdf(monkeypatch):
    small_noise = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=20, y0=80, x1=45, y1=100),
        new_bbox=BBox(page=1, x0=20, y0=80, x1=45, y1=100),
        context="Page 1 圖形差異 (128 px)",
        confidence=0.95,
    )
    old_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    new_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)

    monkeypatch.setattr("services.diff_service.diff_pixels", lambda *_args, **_kwargs: [small_noise])
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

    assert report.total_diffs == 0
    assert report.items == []
    assert report.suppressed_count == 1
    assert "visual_noise_suppressed_final=1" in (report.summary or "")


def test_generate_diff_report_fuses_visual_region_with_alignment_recall(monkeypatch):
    visual_region = DiffItem(
        id="",
        diff_type=DiffType.IMAGE_DIFF,
        old_value=None,
        new_value=None,
        old_bbox=BBox(page=1, x0=20, y0=360, x1=560, y1=460),
        new_bbox=BBox(page=1, x0=20, y0=360, x1=560, y1=460),
        context="Page 1 表格/版面變更",
        confidence=0.95,
    )
    old_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    new_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    old_ocr = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("預定利率3.90%", y0=400, y1=418)],
        tables=[],
        raw_json={},
    )
    new_ocr = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("預定利率4.00%", y0=400, y1=418)],
        tables=[],
        raw_json={},
    )
    calls = iter([old_ocr, new_ocr])

    monkeypatch.setattr("config.settings.enable_image_text_recall", True)
    monkeypatch.setattr("config.settings.image_text_recall_strategy", "alignment")
    monkeypatch.setattr("services.diff_service.diff_pixels", lambda *_args, **_kwargs: [visual_region])
    monkeypatch.setattr("services.diff_service.diff_images", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("services.parser_service.parse_image_pdf_via_mineru_ocr", lambda *_args: next(calls))

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
    assert report.items[0].diff_type == DiffType.NUMBER_MODIFIED
    assert "3.90" in (report.items[0].old_value or "")
    assert "4.00" in (report.items[0].new_value or "")
    assert "visual_fused=1" in (report.summary or "")


def test_generate_diff_report_can_use_alignment_recall_strategy(monkeypatch):
    old_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    new_doc = ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    old_ocr = ParsedDocument(
        pages=1,
        paragraphs=[_paragraph("假設每年宣告利率為3.90%不變情況下計算")],
        tables=[],
        raw_json={},
    )
    new_ocr = ParsedDocument(
        pages=1,
        paragraphs=[
            _paragraph("假設每年宣告利率為"),
            _paragraph("4.00%不變情況下計算", y0=80, y1=95),
        ],
        tables=[],
        raw_json={},
    )
    calls = iter([old_ocr, new_ocr])

    monkeypatch.setattr("config.settings.enable_image_text_recall", True)
    monkeypatch.setattr("config.settings.image_text_recall_strategy", "alignment")
    monkeypatch.setattr("services.diff_service.diff_pixels", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("services.diff_service.diff_images", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("services.parser_service.parse_image_pdf_via_mineru_ocr", lambda *_args: next(calls))

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
    assert report.items[0].diff_type == DiffType.NUMBER_MODIFIED
    assert "OCR對齊:number_change" in report.items[0].context
    assert "recall_strategy=alignment" in (report.summary or "")


def test_generate_diff_report_can_use_hybrid_recall_strategy(monkeypatch):
    clause = (
        "註3:本商品於部分保單年度有基本保險金額對應之身故完全失能保險金"
        "給付逐年遞減之特性當宣告利率低於一定水準時保障可能下降"
    )
    alignment_fragment = DiffItem(
        id="",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="1",
        new_value=clause,
        old_bbox=BBox(page=2, x0=40, y0=600, x1=80, y1=620),
        new_bbox=BBox(page=2, x0=40, y0=600, x1=520, y1=660),
        context="Page 2 內容變更（OCR對齊:number_change）",
        confidence=0.78,
    )
    heuristic_clause = DiffItem(
        id="",
        diff_type=DiffType.ADDED,
        old_value=None,
        new_value=clause,
        old_bbox=None,
        new_bbox=BBox(page=2, x0=40, y0=600, x1=520, y1=660),
        context="Page 2 區塊新增（OCR召回）",
        confidence=0.75,
    )
    old_doc = ParsedDocument(pages=2, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    new_doc = ParsedDocument(pages=2, paragraphs=[], tables=[], raw_json={}, is_image_pdf=True)
    empty_ocr = ParsedDocument(pages=2, paragraphs=[], tables=[], raw_json={})

    monkeypatch.setattr("config.settings.enable_image_text_recall", True)
    monkeypatch.setattr("config.settings.image_text_recall_strategy", "hybrid")
    monkeypatch.setattr("services.diff_service.diff_pixels", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("services.diff_service.diff_images", lambda *_args, **_kwargs: [])
    monkeypatch.setattr("services.diff_service.diff_aligned_paragraphs", lambda *_args, **_kwargs: [alignment_fragment])
    monkeypatch.setattr("services.diff_service.diff_positioned_paragraphs", lambda *_args, **_kwargs: [heuristic_clause])
    monkeypatch.setattr("services.parser_service.parse_image_pdf_via_mineru_ocr", lambda *_args: empty_ocr)

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
    assert report.items[0].diff_type == DiffType.ADDED
    assert "註3" in (report.items[0].new_value or "")
    assert "recall_strategy=hybrid" in (report.summary or "")


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
