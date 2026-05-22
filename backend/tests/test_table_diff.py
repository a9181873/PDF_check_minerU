import pandas as pd

from models.diff_models import BBox, DiffType
from services.diff_service import generate_diff_report
from services.parser_service import ParsedDocument, ParsedTable


def _table(data, page: int = 1) -> ParsedTable:
    return ParsedTable(
        dataframe=pd.DataFrame(data),
        bbox=BBox(page=page, x0=10.0, y0=10.0, x1=300.0, y1=180.0),
        caption="Premium Table",
        header_rows=1,
    )


def test_generate_diff_report_detects_table_cell_change():
    old_doc = ParsedDocument(
        pages=1,
        paragraphs=[],
        tables=[_table({"項目": ["保費"], "數值": ["0.216%"]})],
        raw_json={},
    )
    new_doc = ParsedDocument(
        pages=1,
        paragraphs=[],
        tables=[_table({"項目": ["保費"], "數值": ["0.195%"]})],
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
    assert "Table 1" in report.items[0].context


def test_generate_diff_report_keeps_heavily_changed_numeric_table():
    # A rate table where >=70% of cells change collapses to one aggregate
    # marker. It must survive the final non-numeric filter (regression: identical
    # placeholder old/new used to be dropped) and carry differing values.
    old_doc = ParsedDocument(
        pages=1,
        paragraphs=[],
        tables=[_table({"A": ["1", "2", "3"], "B": ["4", "5", "6"]})],
        raw_json={},
    )
    new_doc = ParsedDocument(
        pages=1,
        paragraphs=[],
        tables=[_table({"A": ["10", "20", "30"], "B": ["40", "50", "60"]})],
        raw_json={},
    )

    report = generate_diff_report(
        project_id="p002",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_doc=old_doc,
        new_doc=new_doc,
    )

    assert report.total_diffs == 1
    item = report.items[0]
    assert "整表替換" in item.context
    assert item.diff_type == DiffType.NUMBER_MODIFIED
    assert item.old_value != item.new_value
