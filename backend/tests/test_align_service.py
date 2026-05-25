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


def test_alignment_suppresses_formula_noise():
    formula = "C V + ∑E n d(1 + i) m-tm=1、5、10、15、20"
    old = [_para(formula, 6)]
    new = []

    assert align_paragraphs(old, new) == []
