from services.parser_service import _span_text


def test_span_text_prefers_span_text_when_present():
    span = {"text": "native text", "chars": [{"c": "x"}]}

    assert _span_text(span) == "native text"


def test_span_text_falls_back_to_rawdict_chars():
    span = {"chars": [{"c": "A"}, {"c": "B"}, {"c": "C"}]}

    assert _span_text(span) == "ABC"
