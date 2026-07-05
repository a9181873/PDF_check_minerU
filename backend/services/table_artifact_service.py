"""Canonical table artifacts and geometry/structure-aware table pairing."""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher

from models.diff_models import BBox, TableArtifact, TableCellArtifact
from services.parser_service import ParsedTable


def _normalize(value: object) -> str:
    return " ".join(re.sub(r"\s+", " ", str(value or "")).strip().lower().split())


def build_table_artifact(table: ParsedTable, *, source: str = "parser") -> TableArtifact:
    rows, columns = table.dataframe.shape
    cells: list[TableCellArtifact] = []
    signature_values: list[str] = [str(rows), str(columns)]
    for row in range(rows):
        for column in range(columns):
            text = _normalize(table.dataframe.iat[row, column])
            if row < 2:
                signature_values.append(text)
            cells.append(
                TableCellArtifact(
                    row=row,
                    column=column,
                    text=text,
                    bbox=table.cell_bboxes.get((row, column)),
                )
            )
    signature = hashlib.sha256("|".join(signature_values).encode("utf-8")).hexdigest()[:16]
    return TableArtifact(
        page=table.bbox.page,
        bbox=table.bbox,
        rows=rows,
        columns=columns,
        cells=cells,
        source=source,
        structure_signature=signature,
    )


def _bbox_iou(a: BBox, b: BBox) -> float:
    if a.page != b.page:
        return 0.0
    x0, y0 = max(a.x0, b.x0), max(a.y0, b.y0)
    x1, y1 = min(a.x1, b.x1), min(a.y1, b.y1)
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    area_a = max(0.0, a.x1 - a.x0) * max(0.0, a.y1 - a.y0)
    area_b = max(0.0, b.x1 - b.x0) * max(0.0, b.y1 - b.y0)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _pair_score(old: TableArtifact, new: TableArtifact) -> float:
    if old.page != new.page:
        return 0.0
    iou = _bbox_iou(old.bbox, new.bbox)
    row_similarity = 1.0 - abs(old.rows - new.rows) / max(old.rows, new.rows, 1)
    column_similarity = 1.0 - abs(old.columns - new.columns) / max(old.columns, new.columns, 1)
    old_head = " ".join(cell.text for cell in old.cells if cell.row < 2)
    new_head = " ".join(cell.text for cell in new.cells if cell.row < 2)
    text_similarity = SequenceMatcher(None, old_head, new_head, autojunk=False).ratio()
    return 0.55 * iou + 0.20 * row_similarity + 0.15 * column_similarity + 0.10 * text_similarity


def pair_tables(
    old_tables: list[ParsedTable],
    new_tables: list[ParsedTable],
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    old_artifacts = [build_table_artifact(table) for table in old_tables]
    new_artifacts = [build_table_artifact(table) for table in new_tables]
    available_new = set(range(len(new_tables)))
    pairs: list[tuple[int, int]] = []
    unmatched_old: list[int] = []

    for old_index, old in enumerate(old_artifacts):
        scored = sorted(
            (
                (_pair_score(old, new_artifacts[new_index]), new_index)
                for new_index in available_new
            ),
            reverse=True,
        )
        if not scored or scored[0][0] < 0.35:
            unmatched_old.append(old_index)
            continue
        _, new_index = scored[0]
        pairs.append((old_index, new_index))
        available_new.remove(new_index)

    return pairs, unmatched_old, sorted(available_new)
