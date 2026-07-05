from pathlib import Path

from config import settings
from models.database import (
    add_review_log,
    create_comparison,
    create_user,
    create_pdf_archive,
    ensure_default_admin,
    ensure_default_project,
    get_archive_by_hashes,
    get_checklist,
    get_comparison_report,
    get_user_by_username,
    get_review_counts,
    get_review_logs,
    get_review_logs_with_changes,
    init_db,
    save_checklist,
    save_analysis_report_state,
    save_comparison_report_state,
    update_review_item_state,
    verify_password,
)
from models.diff_models import CheckStatus, ChecklistItem, DiffItem, DiffReport, DiffType


def _prepare_temp_db(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.db")
    monkeypatch.setattr(settings, "data_dir", tmp_path)


def _create_comparison_record(comparison_id: str) -> None:
    create_comparison(
        comparison_id=comparison_id,
        project_id=ensure_default_project(),
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_file_path="/tmp/old.pdf",
        new_file_path="/tmp/new.pdf",
    )


def test_review_counts_use_latest_action(monkeypatch, tmp_path: Path):
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()
    comparison_id = "cmp-review"
    _create_comparison_record(comparison_id)

    add_review_log(comparison_id, "d001", "confirmed", "alice", None)
    add_review_log(comparison_id, "d001", "flagged", "bob", "recheck")
    add_review_log(comparison_id, "d002", "confirmed", "alice", None)

    counts = get_review_counts(comparison_id)

    assert counts["confirmed"] == 1
    assert counts["flagged"] == 1
    assert counts["skipped"] == 0


def _seed_report(comparison_id: str) -> None:
    report = DiffReport(
        project_id=ensure_default_project(),
        old_filename="old.pdf",
        new_filename="new.pdf",
        created_at="2026-05-25T00:00:00Z",
        total_diffs=2,
        items=[
            DiffItem(id="d001", diff_type=DiffType.NUMBER_MODIFIED, context="p1", confidence=0.9),
            DiffItem(id="d002", diff_type=DiffType.NUMBER_MODIFIED, context="p2", confidence=0.9),
        ],
    )
    save_comparison_report_state(comparison_id, report)


def test_update_review_item_state_is_atomic_per_item(monkeypatch, tmp_path: Path):
    # Two reviewers acting on different items must not clobber each other: updating
    # d001 must leave d002 untouched (the bug was overwriting the whole report blob).
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()
    comparison_id = "cmp-atomic"
    _create_comparison_record(comparison_id)
    _seed_report(comparison_id)

    assert update_review_item_state(
        comparison_id, "d002", reviewed=True, reviewed_by="alice",
        reviewed_at="2026-05-25T01:00:00Z", flagged=False,
    ) is True
    assert update_review_item_state(
        comparison_id, "d001", reviewed=True, reviewed_by="bob",
        reviewed_at="2026-05-25T02:00:00Z", flagged=True,
    ) is True

    report = get_comparison_report(comparison_id)
    by_id = {it.id: it for it in report.items}
    # d001 flagged by bob; d002's earlier confirm by alice survives.
    assert by_id["d001"].reviewed and by_id["d001"].flagged and by_id["d001"].reviewed_by == "bob"
    assert by_id["d002"].reviewed and not by_id["d002"].flagged and by_id["d002"].reviewed_by == "alice"

    # Unknown comparison / item → False, no crash.
    assert update_review_item_state(
        comparison_id, "d999", reviewed=True, reviewed_by="x", reviewed_at="t", flagged=True,
    ) is False


def test_progressive_report_merge_preserves_review_state(monkeypatch, tmp_path: Path):
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()
    comparison_id = "cmp-progressive"
    _create_comparison_record(comparison_id)

    preliminary = DiffReport(
        project_id="default",
        old_filename="old.pdf",
        new_filename="new.pdf",
        created_at="2026-07-04T00:00:00Z",
        total_diffs=1,
        items=[
            DiffItem(
                id="d001",
                candidate_id="c-stable",
                diff_type=DiffType.IMAGE_DIFF,
                context="Page 1 表格/版面變更",
                confidence=0.9,
            )
        ],
    )
    save_analysis_report_state(comparison_id, preliminary)
    assert update_review_item_state(
        comparison_id,
        "d001",
        reviewed=True,
        reviewed_by="alice",
        reviewed_at="2026-07-04T01:00:00Z",
        flagged=False,
    )

    enriched = preliminary.model_copy(deep=True)
    enriched.items[0].old_value = "3.90%"
    enriched.items[0].new_value = "4.00%"
    merged = save_analysis_report_state(comparison_id, enriched, complete=True)

    assert merged.items[0].id == "d001"
    assert merged.items[0].reviewed is True
    assert merged.items[0].reviewed_by == "alice"
    assert merged.report_revision == 2


def test_checklist_round_trip_persists_to_sqlite(monkeypatch, tmp_path: Path):
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()
    comparison_id = "cmp-checklist"
    _create_comparison_record(comparison_id)

    save_checklist(
        comparison_id,
        [
            ChecklistItem(
                item_id="C001",
                check_type="number",
                search_keyword="保單利率",
                expected_old="0.216%",
                expected_new="0.195%",
                status=CheckStatus.CONFIRMED,
                matched_diff_id="d001",
                note="verified",
            )
        ],
    )

    items = get_checklist(comparison_id)

    assert len(items) == 1
    assert items[0].item_id == "C001"
    assert items[0].status == CheckStatus.CONFIRMED
    assert items[0].matched_diff_id == "d001"


def test_review_logs_return_full_timeline(monkeypatch, tmp_path: Path):
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()
    comparison_id = "cmp-log"
    _create_comparison_record(comparison_id)

    add_review_log(comparison_id, "d001", "flagged", "alice", "needs check")
    add_review_log(comparison_id, "d001", "confirmed", "bob", "approved")

    logs = get_review_logs(comparison_id)

    assert len(logs) == 2
    assert logs[0]["action"] == "flagged"
    assert logs[0]["reviewer"] == "alice"
    assert logs[1]["action"] == "confirmed"
    assert logs[1]["note"] == "approved"


def test_review_logs_include_change_summaries(monkeypatch, tmp_path: Path):
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()
    comparison_id = "cmp-log-change"
    _create_comparison_record(comparison_id)

    add_review_log(comparison_id, "d001", "confirmed", "alice", "first pass")
    add_review_log(comparison_id, "d001", "flagged", "bob", "needs check")

    logs = get_review_logs_with_changes(comparison_id)

    assert logs[0]["change_type"] == "created"
    assert logs[1]["change_type"] == "modified"
    assert logs[1]["previous_action"] == "confirmed"
    assert "狀態由" in (logs[1]["change_summary"] or "")


def test_archives_are_separated_by_case_number(monkeypatch, tmp_path: Path):
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()

    create_pdf_archive(
        archive_id="archive-a",
        old_hash="old-hash",
        new_hash="new-hash",
        case_number="CASE-A",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_archive_path="/tmp/case-a-old.pdf",
        new_archive_path="/tmp/case-a-new.pdf",
        annotated_archive_path=None,
        first_comparison_id="cmp-a",
    )
    create_pdf_archive(
        archive_id="archive-b",
        old_hash="old-hash",
        new_hash="new-hash",
        case_number="CASE-B",
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_archive_path="/tmp/case-b-old.pdf",
        new_archive_path="/tmp/case-b-new.pdf",
        annotated_archive_path=None,
        first_comparison_id="cmp-b",
    )

    assert get_archive_by_hashes("old-hash", "new-hash", "CASE-A")["id"] == "archive-a"
    assert get_archive_by_hashes("old-hash", "new-hash", "CASE-B")["id"] == "archive-b"


def test_default_admin_is_fixed_and_does_not_write_initial_password_file(monkeypatch, tmp_path: Path):
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()
    stale_password_file = tmp_path / ".initial_admin_password"
    stale_password_file.write_text("old-secret\n", encoding="utf-8")

    ensure_default_admin()

    admin = get_user_by_username("admin")
    assert admin is not None
    assert admin["role"] == "admin"
    assert admin["is_active"] == 1
    assert verify_password("admin123", admin["password_hash"])
    assert not stale_password_file.exists()


def test_default_admin_resets_existing_admin_to_fixed_credentials(monkeypatch, tmp_path: Path):
    _prepare_temp_db(monkeypatch, tmp_path)
    init_db()
    create_user("admin", "舊管理員", "not-admin123", role="reviewer")

    ensure_default_admin()

    admin = get_user_by_username("admin")
    assert admin is not None
    assert admin["display_name"] == "系統管理員"
    assert admin["role"] == "admin"
    assert admin["is_active"] == 1
    assert verify_password("admin123", admin["password_hash"])
