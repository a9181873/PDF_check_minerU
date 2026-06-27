import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pandas as pd

from config import settings
from models.diff_models import BBox
from services import parser_service
from services.parser_service import (
    ParsedDocument,
    ParsedParagraph,
    ParsedTable,
    _mineru_bbox_to_bbox,
    _parsedocument_from_opendataloader_json,
    _parse_pdf_uncached,
    _probe_page_table_candidates,
    _select_table_document,
    _span_text,
    clear_parse_cache,
    parse_pdf,
)


def test_span_text_prefers_span_text_when_present():
    span = {"text": "native text", "chars": [{"c": "x"}]}

    assert _span_text(span) == "native text"


def test_span_text_falls_back_to_rawdict_chars():
    span = {"chars": [{"c": "A"}, {"c": "B"}, {"c": "C"}]}

    assert _span_text(span) == "ABC"


def test_mineru_bbox_scales_from_0_1000_normalized_space():
    # MinerU content_list bbox is normalised to 0-1000 (top-left origin);
    # it must be scaled by the real page size, then flipped to bottom-left.
    bbox = _mineru_bbox_to_bbox([500, 0, 1000, 100], page_no=2, page_width=600, page_height=800)

    assert bbox.page == 2
    assert bbox.x0 == 300.0  # 500/1000 * 600
    assert bbox.x1 == 600.0  # 1000/1000 * 600
    assert bbox.y1 == 800.0  # 800 - (0/1000 * 800)
    assert bbox.y0 == 720.0  # 800 - (100/1000 * 800)


def test_mineru_bbox_falls_back_to_raw_when_page_size_unknown():
    bbox = _mineru_bbox_to_bbox([10, 20, 30, 40], page_no=1, page_width=0, page_height=0)

    assert bbox.x0 == 10.0
    assert bbox.x1 == 30.0


def _table_document(engine: str) -> ParsedDocument:
    table = ParsedTable(
        dataframe=pd.DataFrame([["100"]], columns=["保費"]),
        bbox=BBox(page=1, x0=10, y0=10, x1=100, y1=100),
    )
    return ParsedDocument(
        pages=1,
        paragraphs=[],
        tables=[table],
        raw_json={"engine": engine},
    )


def test_docling_first_stops_after_first_valid_table(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"pdf")
    calls: list[str] = []

    def fake_docling(_path):
        calls.append("docling")
        return _table_document("docling")

    def fake_mineru(_path, _sizes):
        calls.append("mineru")
        return _table_document("mineru")

    monkeypatch.setattr(settings, "table_parser_strategy", "docling_first")
    monkeypatch.setattr(settings, "mineru_api_url", "http://mineru")
    monkeypatch.setattr(parser_service, "_parse_via_docling", fake_docling)
    monkeypatch.setattr(parser_service, "_parse_via_mineru", fake_mineru)

    selected, routing = _select_table_document(pdf_path, {})

    assert selected is not None
    assert routing["table_engine"] == "docling"
    assert routing["attempts"][0]["status"] == "selected"
    assert calls == ["docling"]


def test_parse_cache_reuses_document_and_marks_hit(monkeypatch, tmp_path):
    clear_parse_cache()
    pdf_path = tmp_path / "same.pdf"
    pdf_path.write_bytes(b"same-content")
    calls = 0

    def fake_parse(_path):
        nonlocal calls
        calls += 1
        return ParsedDocument(
            pages=1,
            paragraphs=[
                ParsedParagraph(
                    text="內容",
                    bbox=BBox(page=1, x0=0, y0=0, x1=10, y1=10),
                )
            ],
            tables=[],
            raw_json={"engine": "test", "routing": {}},
        )

    monkeypatch.setattr(settings, "enable_parser_cache", True)
    monkeypatch.setattr(settings, "parser_cache_max_entries", 2)
    monkeypatch.setattr(parser_service, "_parse_pdf_uncached", fake_parse)

    first = parse_pdf(str(pdf_path))
    second = parse_pdf(str(pdf_path))

    assert calls == 1
    assert first.raw_json["routing"]["cache_hit"] is False
    assert second.raw_json["routing"]["cache_hit"] is True
    clear_parse_cache()


def test_parse_cache_single_flight_deduplicates_parallel_call(monkeypatch, tmp_path):
    clear_parse_cache()
    pdf_path = tmp_path / "parallel.pdf"
    pdf_path.write_bytes(b"parallel-content")
    release = threading.Event()
    entered = threading.Event()
    calls = 0

    def fake_parse(_path):
        nonlocal calls
        calls += 1
        entered.set()
        assert release.wait(timeout=2)
        return ParsedDocument(pages=1, paragraphs=[], tables=[], raw_json={"engine": "test"})

    monkeypatch.setattr(settings, "enable_parser_cache", True)
    monkeypatch.setattr(parser_service, "_parse_pdf_uncached", fake_parse)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(parse_pdf, str(pdf_path))
        assert entered.wait(timeout=2)
        second = pool.submit(parse_pdf, str(pdf_path))
        release.set()
        results = [first.result(timeout=2), second.result(timeout=2)]

    assert calls == 1
    assert sorted(doc.raw_json["routing"]["cache_hit"] for doc in results) == [False, True]
    clear_parse_cache()


def test_opendataloader_json_maps_table_cells_and_bboxes():
    payload = {
        "number of pages": 1,
        "kids": [
            {
                "type": "paragraph",
                "page number": 1,
                "bounding box": [10, 700, 200, 720],
                "content": "保險內容",
            },
            {
                "type": "table",
                "page number": 1,
                "bounding box": [10, 500, 200, 650],
                "number of rows": 2,
                "number of columns": 2,
                "rows": [
                    {
                        "cells": [
                            {
                                "row number": 1,
                                "column number": 1,
                                "kids": [{"content": "項目", "page number": 1, "bounding box": [10, 620, 80, 650]}],
                            },
                            {
                                "row number": 1,
                                "column number": 2,
                                "kids": [{"content": "數值", "page number": 1, "bounding box": [80, 620, 200, 650]}],
                            },
                        ]
                    },
                    {
                        "cells": [
                            {
                                "row number": 2,
                                "column number": 1,
                                "kids": [{"content": "保費", "page number": 1, "bounding box": [10, 500, 80, 620]}],
                            },
                            {
                                "row number": 2,
                                "column number": 2,
                                "kids": [{"content": "100", "page number": 1, "bounding box": [80, 500, 200, 620]}],
                            },
                        ]
                    },
                ],
            },
        ],
    }

    document = _parsedocument_from_opendataloader_json(payload)

    assert document.raw_json["engine"] == "opendataloader"
    assert document.paragraphs[0].text == "保險內容"
    assert len(document.tables) == 1
    assert list(document.tables[0].dataframe.columns) == ["項目", "數值"]
    assert document.tables[0].dataframe.iloc[0].tolist() == ["保費", "100"]
    assert document.tables[0].cell_bboxes[(1, 1)].x0 == 80


def test_lightweight_probe_detects_connected_ruled_grid():
    items = []
    for y in (0, 50, 100, 150):
        items.append(("l", SimpleNamespace(x=0, y=y), SimpleNamespace(x=200, y=y)))
    for x in (0, 100, 200):
        items.append(("l", SimpleNamespace(x=x, y=0), SimpleNamespace(x=x, y=150)))

    class FakePage:
        def get_text(self, mode):
            assert mode == "words"
            return []

        def get_drawings(self):
            return [{"items": items}]

    assert _probe_page_table_candidates(FakePage()) == 1


def test_digital_pdf_without_table_candidate_skips_heavy_parser(monkeypatch, tmp_path):
    pdf_path = tmp_path / "plain.pdf"
    pdf_path.write_bytes(b"pdf")
    digital_doc = ParsedDocument(
        pages=1,
        paragraphs=[ParsedParagraph(text="一般文字", bbox=BBox(page=1, x0=0, y0=0, x1=10, y1=10))],
        tables=[],
        raw_json={
            "engine": "pymupdf",
            "table_candidate_count": 0,
            "table_probe_errors": 0,
        },
    )
    monkeypatch.setattr(settings, "enable_lightweight_table_probe", True)
    monkeypatch.setattr(parser_service, "_parse_via_fitz", lambda _path: digital_doc)
    monkeypatch.setattr(
        parser_service,
        "_select_table_document",
        lambda *_args: (_ for _ in ()).throw(AssertionError("heavy parser must be skipped")),
    )

    parsed = _parse_pdf_uncached(pdf_path)

    assert parsed.raw_json["routing"]["table_strategy"] == "skipped_no_table_candidate"
