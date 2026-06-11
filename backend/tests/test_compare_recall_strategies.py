from models.diff_models import BBox, DiffItem, DiffType
from scripts import compare_recall_strategies as recall_ab
from services.parser_service import ParsedDocument, ParsedParagraph
from services.recall_hybrid_service import build_hybrid_recall_candidates


def _bbox(page: int = 1) -> BBox:
    return BBox(page=page, x0=40, y0=600, x1=520, y1=640)


def _item(
    diff_type: DiffType,
    *,
    old: str | None = None,
    new: str | None = None,
    page: int = 1,
    context: str = "Page 1 內容變更（OCR對齊:number_change）",
) -> DiffItem:
    return DiffItem(
        id="",
        diff_type=diff_type,
        old_value=old,
        new_value=new,
        old_bbox=_bbox(page) if old else None,
        new_bbox=_bbox(page) if new else None,
        context=context,
        confidence=0.78,
    )


def test_ocr_cache_reuses_parsed_document(tmp_path, monkeypatch):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF fake bytes for cache key")
    cache_dir = tmp_path / "ocr-cache"
    calls = {"count": 0}

    doc = ParsedDocument(
        pages=1,
        paragraphs=[ParsedParagraph(text="台灣人壽商品文號", bbox=_bbox())],
        tables=[],
        raw_json={"engine": "mineru"},
        is_image_pdf=True,
    )

    def fake_parse(path: str):
        calls["count"] += 1
        assert path == str(pdf)
        return doc

    monkeypatch.setattr(recall_ab, "parse_image_pdf_via_mineru_ocr", fake_parse)

    first, first_status = recall_ab.parse_image_pdf_with_cache(pdf, cache_dir)
    second, second_status = recall_ab.parse_image_pdf_with_cache(pdf, cache_dir)

    assert first_status == "miss"
    assert second_status == "hit"
    assert calls["count"] == 1
    assert first.paragraphs[0].text == second.paragraphs[0].text


def test_hybrid_prefers_heuristic_long_clause_over_alignment_fragments():
    clause = (
        "註3:本商品於部分保單年度有基本保險金額對應之身故完全失能保險金"
        "給付逐年遞減之特性當宣告利率低於一定水準時保障可能下降"
    )
    alignment = [
        _item(DiffType.NUMBER_MODIFIED, old="1", new=clause, page=2),
        _item(
            DiffType.DELETED,
            old="註3:身故保險金完全失能保險金的給付可選擇分期定期給付本範例數值僅供參考",
            page=2,
            context="Page 2 區塊刪除（OCR對齊:number_change）",
        ),
    ]
    heuristic = [
        _item(
            DiffType.ADDED,
            new=clause,
            page=2,
            context="Page 2 區塊新增（OCR召回）",
        )
    ]

    hybrid = build_hybrid_recall_candidates(alignment, heuristic)

    assert len(hybrid) == 1
    assert hybrid[0].source_strategy == "heuristic"
    assert hybrid[0].item.diff_type == DiffType.ADDED


def test_hybrid_suppresses_customer_service_phone_fragment():
    alignment = [
        _item(
            DiffType.ADDED,
            new="客服務專線:0800-099-850/手機另撥:(02)8170-5156",
            context="Page 4 區塊新增（OCR對齊:number_change）",
        )
    ]

    assert build_hybrid_recall_candidates(alignment, []) == []


def test_hybrid_keeps_alignment_date_or_document_number_change():
    alignment = [
        _item(
            DiffType.NUMBER_MODIFIED,
            old="商品號:中華民國113年321日台壽字第1132320022號函備查",
            new="商品號:中華民國113年3月21日台壽字第1132320022號函備查",
        )
    ]

    hybrid = build_hybrid_recall_candidates(alignment, [])

    assert len(hybrid) == 1
    assert hybrid[0].source_strategy == "alignment"
    assert hybrid[0].item.diff_type == DiffType.NUMBER_MODIFIED


def test_hybrid_deduplicates_compact_and_full_date_number_change():
    alignment = [
        _item(DiffType.NUMBER_MODIFIED, old="321", new="3月21")
    ]
    heuristic = [
        _item(
            DiffType.NUMBER_MODIFIED,
            old="商品號:中華民國113年321日台壽字第1132320022號函備查",
            new="商品號:中華民國113年3月21日台壽字第1132320022號函備查",
            context="Page 1 內容變更（OCR召回）",
        )
    ]

    hybrid = build_hybrid_recall_candidates(alignment, heuristic)

    assert len(hybrid) == 1
    assert hybrid[0].source_strategy == "heuristic"
