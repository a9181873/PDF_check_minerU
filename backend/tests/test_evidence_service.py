from models.diff_models import (
    AnalysisStage,
    BBox,
    DiffItem,
    DiffType,
    ReviewLane,
    RiskLevel,
)
from services.evidence_service import annotate_diff_items, stable_candidate_id


def test_candidate_id_is_stable_across_tiny_bbox_drift():
    first = DiffItem(
        id="d001",
        diff_type=DiffType.IMAGE_DIFF,
        old_bbox=BBox(page=2, x0=10.1, y0=20.2, x1=200.1, y1=300.1),
        new_bbox=BBox(page=2, x0=10.1, y0=20.2, x1=200.1, y1=300.1),
        context="Page 2 表格/版面變更",
        confidence=0.9,
    )
    second = first.model_copy(deep=True)
    second.new_bbox.x0 = 10.3

    assert stable_candidate_id(first) == stable_candidate_id(second)


def test_visual_evidence_enters_review_lane_and_numeric_is_critical():
    visual = DiffItem(
        id="d001",
        diff_type=DiffType.IMAGE_DIFF,
        old_bbox=BBox(page=1, x0=10, y0=20, x1=200, y1=300),
        new_bbox=BBox(page=1, x0=10, y0=20, x1=200, y1=300),
        context="Page 1 表格/版面變更",
        confidence=0.9,
    )
    numeric = DiffItem(
        id="d002",
        diff_type=DiffType.NUMBER_MODIFIED,
        old_value="3.90%",
        new_value="4.00%",
        context="宣告利率",
        confidence=0.9,
    )

    annotate_diff_items([visual, numeric], stage=AnalysisStage.PRELIMINARY)

    assert visual.review_lane == ReviewLane.NEEDS_VISUAL_REVIEW
    assert visual.risk_level == RiskLevel.HIGH
    assert visual.evidence[0].kind == "image_diff"
    assert numeric.review_lane == ReviewLane.CONTENT
    assert numeric.risk_level == RiskLevel.CRITICAL
