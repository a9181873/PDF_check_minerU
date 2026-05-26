from types import SimpleNamespace

from models.diff_models import BBox
from services.align_service import align_paragraphs


def _para(text: str, page: int, x0: float = 40, y0: float = 700):
    return SimpleNamespace(
        text=text,
        bbox=BBox(page=page, x0=x0, y0=y0, x1=x0 + 420, y1=y0 + 20),
        char_bboxes=None,
    )


def test_alignment_reports_numeric_change_across_resegmentation():
    old = [_para("假設每年宣告利率為3.90%不變情況下計算", 1)]
    new = [
        _para("假設每年宣告利率為", 1),
        _para("4.00%不變情況下計算", 1, y0=670),
    ]

    items = align_paragraphs(old, new)

    assert len(items) == 1
    assert items[0].kind == "modified"
    assert items[0].reason == "number_change"
    assert "3" in (items[0].old_text or "")
    assert "4" in (items[0].new_text or "")


def test_alignment_ignores_numeric_separator_drift():
    old = [_para("假設每年宣告利率3.90%計算", 1)]
    new = [_para("假設每年宣告利率3,90%計算", 1)]

    assert align_paragraphs(old, new) == []


def test_alignment_reports_large_added_cjk_clause():
    shared = "住院日額保險金被保險人於本契約有效期間內因疾病住院"
    clause = "訂立本契約時以受監護宣告尚未撤銷者為被保險人其身故保險金變更為喪葬費用保險金"
    old = [_para(shared, 2)]
    new = [_para(shared, 2), _para(clause, 2, y0=620)]

    items = align_paragraphs(old, new)

    assert len(items) == 1
    assert items[0].kind == "added"
    assert items[0].reason == "large_cjk_added"
    assert "監護宣告" in (items[0].new_text or "")


def test_alignment_merges_nearby_header_number_changes():
    old = [_para("中華民國112年9月11日金管保壽字第1110152342號函修正", 1)]
    new = [_para("中華民國113年7月27日金管保壽字第11304921175號函修正", 1)]

    items = align_paragraphs(old, new)

    assert len(items) == 1
    assert items[0].kind == "modified"
    assert "112" in (items[0].old_text or "")
    assert "1110152342" in (items[0].old_text or "")
    assert "113" in (items[0].new_text or "")
    assert "11304921175" in (items[0].new_text or "")


def test_alignment_suppresses_moved_identical_clause():
    first = "台灣人壽新扶愛微型傷害保險商品名稱"
    moved = "將要保書連同資格證明文件送交代理投保單位完成集體投保作業"
    old = [_para(first, 1), _para(moved, 1, y0=660)]
    new = [_para(moved, 1), _para(first, 1, y0=660)]

    assert align_paragraphs(old, new) == []


def test_alignment_drops_tiny_one_sided_number_heading():
    assert align_paragraphs([], [_para("8注意事項", 4)]) == []


def test_alignment_keeps_one_sided_amount_change():
    items = align_paragraphs([], [_para("給付祝壽保險金1,448,275.00美元", 3)])

    assert len(items) == 1
    assert items[0].kind == "added"
    assert items[0].reason == "number_change"


def test_alignment_expands_decimal_rate_token():
    old = [_para("分期定期保險金預定利率為2.25%。", 2)]
    new = [_para("分期定期保險金預定利率為2.50%。", 2)]

    items = align_paragraphs(old, new)

    assert len(items) == 1
    assert items[0].kind == "modified"
    assert "2.25%" in (items[0].old_text or "")
    assert "2.50%" in (items[0].new_text or "")


def test_alignment_suppresses_formula_noise():
    formula = "C V + ∑E n d(1 + i) m-tm=1、5、10、15、20"
    old = [_para(formula, 6)]
    new = []

    assert align_paragraphs(old, new) == []
