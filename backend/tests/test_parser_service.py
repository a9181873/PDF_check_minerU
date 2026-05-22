from services.parser_service import _mineru_bbox_to_bbox, _span_text


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
