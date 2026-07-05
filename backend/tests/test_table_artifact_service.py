import pandas as pd

from models.diff_models import BBox
from services.parser_service import ParsedTable
from services.table_artifact_service import build_table_artifact, pair_tables


def _table(page: int, x0: float, title: str) -> ParsedTable:
    return ParsedTable(
        dataframe=pd.DataFrame([[title, "費率"], ["A", "3.9%"]]),
        bbox=BBox(page=page, x0=x0, y0=100, x1=x0 + 200, y1=300),
    )


def test_table_artifact_contains_structure_and_cells():
    artifact = build_table_artifact(_table(1, 10, "商品"), source="docling")
    assert artifact.rows == 2
    assert artifact.columns == 2
    assert len(artifact.cells) == 4
    assert artifact.structure_signature


def test_table_pairing_uses_geometry_not_list_order():
    old = [_table(1, 10, "左表"), _table(1, 350, "右表")]
    new = [_table(1, 351, "右表"), _table(1, 11, "左表")]

    pairs, missing_old, missing_new = pair_tables(old, new)

    assert pairs == [(0, 1), (1, 0)]
    assert missing_old == []
    assert missing_new == []
