import io

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from models.diff_models import BBox, DiffItem, DiffType
from services import diff_service
from services.visual_match_service import compare_patch


def _raster(text):
    image = Image.new("L", (95, 55), 255)
    font = ImageFont.load_default(size=30)
    ImageDraw.Draw(image).text((5, 5), text, fill=0, font=font)
    return np.array(image)


@pytest.mark.parametrize("old,new", [("24", "28"), ("14", "15"), ("3.9", "4.0"), ("70", "7.0"), ("20", "2.0"), ("3.9", "39")])
def test_small_numeric_edits_survive_glyph_noise_filter(old, new):
    score, noise = compare_patch(_raster(old), _raster(new))
    assert score < 0.985
    assert not noise


def test_reencoded_identical_digits_are_rendering_noise():
    old = _raster("24")
    buffer = io.BytesIO()
    Image.fromarray(old).save(buffer, "JPEG", quality=60)
    new = np.array(Image.open(io.BytesIO(buffer.getvalue())))
    score, noise = compare_patch(old, new)
    assert score > 0.985 or noise


def test_completed_roi_reads_are_reused_but_failure_is_retried(monkeypatch):
    calls = []
    payload = (1, 1, b"\xff")
    with diff_service._OCR_ROI_CACHE_LOCK:
        diff_service._OCR_ROI_CACHE.clear()

    def fake(_payload, *, on_result, **_kwargs):
        calls.append(1)
        status = "timeout" if len(calls) == 1 else "complete"
        text = "" if status == "timeout" else "Control No: OP-2605-0029"
        on_result(diff_service.OcrRasterResult(text, status))
        return text

    monkeypatch.setattr(diff_service, "_ocr_raster_payload_uncached", fake)
    outcomes = []
    assert diff_service._ocr_raster_payload(payload, on_result=outcomes.append) == ""
    assert diff_service._ocr_raster_payload(payload, on_result=outcomes.append).endswith("0029")
    assert diff_service._ocr_raster_payload(payload, on_result=outcomes.append).endswith("0029")
    assert len(calls) == 2
    assert outcomes[-1].cached is True
    with diff_service._OCR_ROI_CACHE_LOCK:
        diff_service._OCR_ROI_CACHE.clear()


def test_content_merge_keeps_small_value_bbox_and_uncertain_table_separate():
    table = DiffItem(id="", diff_type=DiffType.IMAGE_DIFF, context="Page 1 表格/版面變更",
        new_bbox=BBox(page=1, x0=0, y0=0, x1=500, y1=600), confidence=0.95)
    value = DiffItem(id="", diff_type=DiffType.NUMBER_MODIFIED, context="Page 1 數字修改",
        old_value="24", new_value="28", new_bbox=BBox(page=1, x0=10, y0=30, x1=40, y1=50), confidence=0.9)
    merged = diff_service.merge_diff_results([], [], [table, value], keep_image_diffs=True, content_first=True)
    assert len(merged) == 2
    numeric = next(i for i in merged if i.diff_type == DiffType.NUMBER_MODIFIED)
    assert numeric.new_bbox == value.new_bbox


def test_visual_cluster_cannot_grow_down_page_by_transitive_links():
    items = [DiffItem(id="", diff_type=DiffType.IMAGE_DIFF, context="Page 1 表格/版面變更",
        new_bbox=BBox(page=1, x0=10, y0=y, x1=200, y1=y+35), confidence=0.9)
        for y in (10, 50, 90, 130)]
    result = diff_service._coalesce_reviewable_visual_items(items)
    assert len(result) >= 2
    assert all(item.new_bbox.y1-item.new_bbox.y0 <= 80 for item in result)


def test_wording_change_with_unchanged_numbers_is_not_numeric_change():
    assert diff_service._guess_diff_type("投保年齡20歲男性", "投保年齡20歲女性") == DiffType.TEXT_MODIFIED
    assert diff_service._guess_diff_type("20歲投保30年", "30歲投保20年") == DiffType.NUMBER_MODIFIED


def test_complete_priority_field_deduplicates_local_partial_reads():
    complete = DiffItem(id="", diff_type=DiffType.NUMBER_MODIFIED,
        old_value="Version: 2025.01; Control No: OP-2501-0029", new_value="Version: 2025.09; Control No: OP-2508-0594",
        new_bbox=BBox(page=1, x0=400, y0=10, x1=580, y1=45), context="Page 1 footer control/version", confidence=.98)
    partial = DiffItem(id="", diff_type=DiffType.NUMBER_MODIFIED, old_value="Version: 2025.01", new_value="Version: 2025.09",
        new_bbox=BBox(page=1, x0=510, y0=20, x1=565, y1=30), context="Page 1 內容變更", confidence=.95)
    result = diff_service.merge_diff_results([], [], [complete, partial], content_first=True)
    assert len(result) == 1
    assert result[0].new_value == complete.new_value


def test_new_embedded_image_is_not_a_text_addition(tmp_path):
    import fitz
    from services.evidence_service import annotate_diff_items
    from models.diff_models import AnalysisStage

    buffer = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(buffer, "PNG")
    for side in ("old", "new"):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((20, 40), "Unchanged native text")
            if side == "new":
                page.insert_image(fitz.Rect(60, 60, 80, 80), stream=buffer.getvalue())
            doc.save(tmp_path / f"{side}.pdf")
    items = diff_service.diff_images(str(tmp_path/"old.pdf"), str(tmp_path/"new.pdf"))
    annotate_diff_items(items, stage=AnalysisStage.FINAL)
    assert len(items) == 1
    assert items[0].diff_type == DiffType.IMAGE_DIFF
    assert items[0].review_lane.value == "needs_visual_review"
