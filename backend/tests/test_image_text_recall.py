"""Unit tests for the image-only PDF text-recall layer.

These cover the pure, position-aligned diff algorithm with synthetic paragraphs
(no MinerU / real PDF needed). End-to-end recall quality and threshold tuning
still require the fixed-sample container regression (see docs/historical_issues.md §7).
"""

from models.diff_models import BBox, DiffType
from services.diff_service import _bbox_iou, diff_positioned_paragraphs
from services.parser_service import ParsedParagraph


def _para(text: str, page: int, x0: float, y0: float, x1: float, y1: float) -> ParsedParagraph:
    return ParsedParagraph(text=text, bbox=BBox(page=page, x0=x0, y0=y0, x1=x1, y1=y1))


def test_bbox_iou_basic():
    a = BBox(page=1, x0=0, y0=0, x1=10, y1=10)
    assert _bbox_iou(a, a) == 1.0
    assert _bbox_iou(a, BBox(page=1, x0=20, y0=20, x1=30, y1=30)) == 0.0
    # same coords, different page → no overlap
    assert _bbox_iou(a, BBox(page=2, x0=0, y0=0, x1=10, y1=10)) == 0.0


def test_recall_recovers_added_clause_block():
    # An added long-CJK clause appears only in the new document; the unchanged
    # block at the same position must not diff, the new block must be ADDED.
    shared = "住院日額保險金被保險人於本契約有效期間內因疾病住院"
    clause = "訂立本契約時以受監護宣告尚未撤銷者為被保險人其身故保險金變更為喪葬費用保險金"
    old_paras = [_para(shared, 2, 50, 600, 500, 620)]
    new_paras = [
        _para(shared, 2, 50, 600, 500, 620),
        _para(clause, 2, 50, 400, 500, 430),
    ]

    items = diff_positioned_paragraphs(old_paras, new_paras)

    assert len(items) == 1
    assert items[0].diff_type == DiffType.ADDED
    assert items[0].new_value and "監護宣告" in items[0].new_value
    assert items[0].old_value is None


def test_recall_reports_numeric_block_change():
    old_paras = [_para("年繳應繳保險費總和32000元", 1, 60, 500, 400, 520)]
    new_paras = [_para("年繳應繳保險費總和31680元", 1, 60, 500, 400, 520)]

    items = diff_positioned_paragraphs(old_paras, new_paras)

    assert len(items) == 1
    assert items[0].diff_type == DiffType.NUMBER_MODIFIED
    assert "32000" in items[0].old_value
    assert "31680" in items[0].new_value


def test_recall_suppresses_ocr_garbage():
    # Bracketed uppercase noise (the `[PAYV` class) must never be surfaced.
    old_paras = [_para("[PAYV qx", 1, 60, 500, 200, 520)]
    new_paras = [_para("[QXZ ww", 1, 60, 500, 200, 520)]

    assert diff_positioned_paragraphs(old_paras, new_paras) == []


def test_recall_ignores_identical_text_at_same_position():
    same = "本保險為不分紅保險單不參加紅利分配亦無紅利給付項目"
    old_paras = [_para(same, 1, 40, 700, 480, 720)]
    new_paras = [_para(same, 1, 40, 700, 480, 720)]

    assert diff_positioned_paragraphs(old_paras, new_paras) == []


def test_recall_collapses_wholesale_page_redesign():
    # A page whose content is almost entirely different (a full redesign) must be
    # flagged in full as ONE comprehensive marker, not fragmented or suppressed.
    old_paras = [
        _para("本保險為不分紅保險單不參加紅利分配亦無紅利給付項目之說明", 1, 40, 700, 540, 720),
        _para("被保險人於本契約有效期間內因疾病或傷害住院診療之給付規定", 1, 40, 600, 540, 680),
    ]
    new_paras = [
        _para("全新改版保障內容與費率結構採用完全不同的最新版本說明文字", 1, 40, 700, 540, 720),
        _para("投保規則商品特色與各項給付項目全面更新請參閱最新保單條款", 1, 40, 600, 540, 680),
    ]

    items = diff_positioned_paragraphs(old_paras, new_paras)

    assert len(items) == 1
    assert "整頁版面變更" in items[0].context
    assert items[0].old_value != items[0].new_value


def test_recall_resegmentation_does_not_false_add_delete():
    # Same sentence, moved to a non-overlapping bbox (OCR re-segmentation). The
    # text-similarity fallback must re-pair it → no false ADDED+DELETED.
    sentence = "被保險人於本契約有效期間內因疾病或傷害而住院診療時台灣人壽依約給付保險金"
    old_paras = [_para(sentence, 1, 50, 600, 520, 620)]
    new_paras = [_para(sentence, 1, 50, 540, 520, 560)]  # shifted down, no overlap

    assert diff_positioned_paragraphs(old_paras, new_paras) == []


def test_recall_ignores_numeric_separator_ocr_drift():
    # '3.90%' vs '3,90%' is OCR decimal/thousands drift between the two scans,
    # not a real change → must be suppressed.
    old_paras = [_para("假設每年宣告利率3.90%計算之累計增加保險金額相關數值", 1, 40, 700, 500, 720)]
    new_paras = [_para("假設每年宣告利率3,90%計算之累計增加保險金額相關數值", 1, 40, 700, 500, 720)]

    assert diff_positioned_paragraphs(old_paras, new_paras) == []


def test_recall_suppresses_high_similarity_ocr_noise():
    # Same block, only an OCR bracket drift ')' → '】' and no numeric change.
    # High similarity + no real number change → OCR noise, must be suppressed.
    old_paras = [_para("假設每年宣告利率3.90%(非保證利率)下計算且為人工試算容有四舍五入之誤差", 1, 40, 700, 500, 720)]
    new_paras = [_para("假設每年宣告利率3.90%(非保證利率】下計算且為人工試算容有四舍五入之誤差", 1, 40, 700, 500, 720)]

    assert diff_positioned_paragraphs(old_paras, new_paras) == []


def test_recall_keeps_real_numeric_change_despite_high_similarity():
    # Same long block, only a rate digit changed (3.90% → 4.20%). High textual
    # similarity but a REAL numeric change → must still be reported.
    old_paras = [_para("假設每年宣告利率3.90%下計算之累計增加保險金額相關數值假設", 1, 40, 700, 500, 720)]
    new_paras = [_para("假設每年宣告利率4.20%下計算之累計增加保險金額相關數值假設", 1, 40, 700, 500, 720)]

    items = diff_positioned_paragraphs(old_paras, new_paras)

    assert len(items) == 1
    assert items[0].diff_type == DiffType.NUMBER_MODIFIED


def test_recall_suppresses_resegmented_added_block_contained_in_old():
    # A footer phone line that, in the new doc, OCR split into its own block but in
    # the old doc is part of a larger block → contained in old page → not an ADD.
    big = "公司地址台北市南港區客戶服務專線0800099850手機另撥0281705156為社會建立完整風險規劃體系"
    phone = "客戶服務專線0800099850手機另撥0281705156"
    old_paras = [_para(big, 1, 40, 600, 520, 700)]
    new_paras = [
        _para(big, 1, 40, 600, 520, 700),
        _para(phone, 1, 40, 500, 300, 520),
    ]

    assert diff_positioned_paragraphs(old_paras, new_paras) == []
