"""Regression coverage for real breaking contracts in the parser core upgrade."""
from types import SimpleNamespace

import pytest
import requests

from config import settings
from services import parser_service


def middle_json():
    return {
        "schema": "docvortex.middle", "schema_version": "2.0", "is_full_document": True,
        "metadata": {"producer": {"version": "4.0.12"}},
        "pages": [{"page_idx": 1, "blocks": [
            {"type": "text", "bbox": [0.1, 0.2, 0.5, 0.3],
             "content": [{"type": "text", "content": "保費_"}, {"type": "text", "content": "100"}]},
            {"type": "table", "bbox": [0.1, 0.4, 0.9, 0.8], "content": [
                {"type": "table_body", "content": "<table><tr><td>保費</td><td>100</td></tr></table>"},
                {"type": "table_caption", "content": [{"type": "text", "content": "保費表"}]},
            ]},
        ]}],
    }


def response(status, payload):
    return SimpleNamespace(status_code=status, json=lambda: payload, raise_for_status=lambda: None)


def completed(middle):
    return {"task_id": "task-1", "status": "completed", "files": [
        {"status": "completed", "content": {"markdown": "保費表", "middle_json": middle}},
    ]}


class FakeSession:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.posts = []
        self.gets = []
        self.deletes = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return next(self.replies)

    def get(self, url, **kwargs):
        self.gets.append(url)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def delete(self, url, **kwargs):
        self.deletes.append(url)


def test_v4_polling_preserves_native_text_tables_and_coordinates(monkeypatch, tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"pdf")
    session = FakeSession([response(202, {"task_id": "task-1"}), response(200, completed(middle_json()))])
    monkeypatch.setattr(requests, "Session", lambda: session)
    monkeypatch.setattr(parser_service.time, "sleep", lambda _: None)
    monkeypatch.setattr(settings, "mineru_api_url", "http://mineru")
    monkeypatch.setattr(settings, "mineru_api_version", "v1")
    parsed = parser_service._parse_via_mineru(pdf, {1: (600, 800), 2: (600, 800)})
    assert len(session.posts) == 1
    assert session.posts[0][0] == "http://mineru/v1/file_parse"
    assert ("page_range", "all") in session.posts[0][1]["params"]
    assert ("tier", "basic") in session.posts[0][1]["params"]
    assert session.gets == ["http://mineru/v1/tasks/task-1/result"]
    assert parsed.paragraphs[0].text == "保費_100"
    assert parsed.paragraphs[0].bbox.model_dump() == {"page": 2, "x0": 60.0, "y0": 560.0, "x1": 300.0, "y1": 640.0}
    assert parsed.tables[0].dataframe.iloc[0].tolist() == ["保費", "100"]
    assert parsed.tables[0].caption == "保費表"
    assert parsed.raw_json["engine_version"] == "4.0.12"


@pytest.mark.parametrize("kind", ["partial", "schema", "incomplete"])
def test_v4_rejects_partial_or_incompatible_results(monkeypatch, tmp_path, kind):
    middle = middle_json()
    result = completed(middle)
    if kind == "partial":
        result["status"] = "partial"
    elif kind == "schema":
        middle["schema_version"] = "3.0"
    else:
        middle["is_full_document"] = False
    session = FakeSession([response(200, result)])
    monkeypatch.setattr(requests, "Session", lambda: session)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"pdf")
    with pytest.raises(RuntimeError):
        parser_service._request_mineru_v4("http://mineru", pdf, "auto", 5)


def test_v4_poll_timeout_cancels_only_its_own_task(monkeypatch, tmp_path):
    session = FakeSession([response(202, {"task_id": "task-1"}), requests.Timeout()])
    monkeypatch.setattr(requests, "Session", lambda: session)
    monkeypatch.setattr(parser_service.time, "sleep", lambda _: None)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"pdf")
    with pytest.raises(requests.Timeout):
        parser_service._request_mineru_v4("http://mineru", pdf, "ocr", 5)
    assert session.deletes == ["http://mineru/v1/tasks/task-1"]
    assert ("ocr_mode", "ocr") in session.posts[0][1]["params"]


@pytest.mark.parametrize("bbox", [[0, 0, 0, 1], [0, 0, 2, 1], [0, 0, float("nan"), 1]])
def test_v4_invalid_bbox_cannot_create_review_coordinates(bbox):
    middle = middle_json()
    middle["pages"][0]["blocks"][0]["bbox"] = bbox
    assert parser_service._mineru_v4_content_list(middle)[0]["bbox"] is None


def test_docling_current_cell_offsets_and_direct_bbox_are_preserved(monkeypatch, tmp_path):
    box = SimpleNamespace(l=10, t=20, r=40, b=50, coord_origin=SimpleNamespace(value="TOPLEFT"))
    cell = SimpleNamespace(start_row_offset_idx=1, start_col_offset_idx=2, bbox=box)
    table = SimpleNamespace(prov=[SimpleNamespace(page_no=1, bbox=box)], data=SimpleNamespace(table_cells=[cell]))
    doc = SimpleNamespace(pages={1: SimpleNamespace(size=SimpleNamespace(height=800))}, tables=[table], iterate_items=lambda: [])
    monkeypatch.setattr(parser_service, "_get_docling_converter", lambda: SimpleNamespace(convert=lambda _: SimpleNamespace(document=doc)))
    parsed = parser_service._parse_via_docling(tmp_path / "table.pdf")
    assert parsed.tables[0].cell_bboxes[(1, 2)].model_dump() == {"page": 1, "x0": 10.0, "y0": 750.0, "x1": 40.0, "y1": 780.0}


def test_v4_keeps_headers_footers_and_nested_list_references():
    middle = middle_json()
    box = [0.1, 0.1, 0.8, 0.2]
    middle["pages"][0]["blocks"] = [
        {"type": kind, "bbox": box, "content": [{"type": "text", "content": text}]}
        for kind, text in [("header", "保險商品"), ("footer", "Control No: 1140815")]
    ] + [{"type": "list", "content": [
        {"type": "list", "content": [{"type": "ref_text", "bbox": box, "content": [{"type": "text", "content": "參照條款"}]}]},
    ]}]
    assert [b["text"] for b in parser_service._mineru_v4_content_list(middle)] == ["保險商品", "Control No: 1140815", "參照條款"]
