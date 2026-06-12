from pathlib import Path

from fastapi.testclient import TestClient

from api.routes_auth import create_token
from config import settings
from main import app
from models.database import (
    create_comparison,
    create_user,
    ensure_default_project,
    get_archive_by_comparison,
    get_comparison_report,
    get_review_logs,
    get_verification_sessions_by_archive,
    init_db,
    save_comparison_report_state,
    save_checklist,
    update_comparison_status,
)
from models.diff_models import CheckStatus, ChecklistItem, DiffItem, DiffReport, DiffType


def _prepare_temp_app(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "db_path", tmp_path / "app.db")
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "archive_dir", tmp_path / "archives")
    monkeypatch.setattr(settings, "old_upload_dir", tmp_path / "uploads" / "old")
    monkeypatch.setattr(settings, "new_upload_dir", tmp_path / "uploads" / "new")
    monkeypatch.setattr(settings, "export_dir", tmp_path / "exports")
    monkeypatch.setattr(settings, "markdown_export_dir", tmp_path / "markdown")


def _auth_headers(user: dict) -> dict[str, str]:
    token = create_token(user["id"], user["username"], user["role"])
    return {"Authorization": f"Bearer {token}"}


def _seed_done_comparison(comparison_id: str, tmp_path: Path) -> None:
    old_path = tmp_path / f"{comparison_id}_old.pdf"
    new_path = tmp_path / f"{comparison_id}_new.pdf"
    old_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    new_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    create_comparison(
        comparison_id=comparison_id,
        project_id=ensure_default_project(),
        old_filename="old.pdf",
        new_filename="new.pdf",
        old_file_path=str(old_path),
        new_file_path=str(new_path),
        case_number="CASE-001",
    )
    update_comparison_status(comparison_id, "done", completed=True)
    save_comparison_report_state(
        comparison_id,
        DiffReport(
            project_id=ensure_default_project(),
            case_number="CASE-001",
            old_filename="old.pdf",
            new_filename="new.pdf",
            created_at="2026-06-13T00:00:00+00:00",
            total_diffs=1,
            items=[
                DiffItem(
                    id="d001",
                    diff_type=DiffType.TEXT_MODIFIED,
                    old_value="舊文字",
                    new_value="新文字",
                    context="測試段落",
                    confidence=0.95,
                )
            ],
        ),
    )


def test_review_action_uses_authenticated_user_not_payload_reviewer(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    _seed_done_comparison("cmp-review-route", tmp_path)
    reviewer = create_user("alice", "王小明", "secret")

    with TestClient(app) as client:
        response = client.post(
            "/api/review/cmp-review-route/confirm",
            headers=_auth_headers(reviewer),
            json={
                "diff_item_id": "d001",
                "action": "confirmed",
                "reviewer": "冒名審核者",
                "note": "已核對",
            },
        )

    assert response.status_code == 200
    assert response.json()["reviewer"] == "王小明"

    logs = get_review_logs("cmp-review-route")
    assert logs[0]["reviewer"] == "王小明"
    assert logs[0]["note"] == "已核對"

    report = get_comparison_report("cmp-review-route")
    assert report.items[0].reviewed is True
    assert report.items[0].reviewed_by == "王小明"


def test_archive_verify_uses_authenticated_user_not_payload_reviewer(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    _seed_done_comparison("cmp-archive-route", tmp_path)
    reviewer = create_user("bob", "李主管", "secret")

    with TestClient(app) as client:
        review_response = client.post(
            "/api/review/cmp-archive-route/confirm",
            headers=_auth_headers(reviewer),
            json={"diff_item_id": "d001", "action": "confirmed"},
        )
        assert review_response.status_code == 200

        response = client.post(
            "/api/archive/cmp-archive-route/verify",
            headers=_auth_headers(reviewer),
            json={"reviewer": "冒名封存者", "notes": "封存確認"},
        )

    assert response.status_code == 200
    archive = get_archive_by_comparison("cmp-archive-route")
    sessions = get_verification_sessions_by_archive(archive["id"])
    assert sessions[0]["reviewer"] == "李主管"
    assert sessions[0]["notes"] == "封存確認"


def test_archive_verify_blocks_pending_review_items(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    _seed_done_comparison("cmp-pending-archive", tmp_path)
    reviewer = create_user("pending-user", "待審人員", "secret")

    with TestClient(app) as client:
        response = client.post(
            "/api/archive/cmp-pending-archive/verify",
            headers=_auth_headers(reviewer),
            json={},
        )

    assert response.status_code == 409
    assert "待審差異" in response.json()["detail"]


def test_archive_verify_blocks_flagged_items(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    _seed_done_comparison("cmp-flagged-archive", tmp_path)
    reviewer = create_user("flag-user", "異常審核", "secret")

    with TestClient(app) as client:
        flag_response = client.post(
            "/api/review/cmp-flagged-archive/confirm",
            headers=_auth_headers(reviewer),
            json={"diff_item_id": "d001", "action": "flagged", "note": "需確認"},
        )
        assert flag_response.status_code == 200

        response = client.post(
            "/api/archive/cmp-flagged-archive/verify",
            headers=_auth_headers(reviewer),
            json={},
        )

    assert response.status_code == 409
    assert "標記問題" in response.json()["detail"]


def test_archive_verify_blocks_unresolved_checklist(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    comparison_id = "cmp-checklist-archive"
    _seed_done_comparison(comparison_id, tmp_path)
    reviewer = create_user("check-user", "清單審核", "secret")
    save_checklist(
        comparison_id,
        [
            ChecklistItem(
                item_id="C001",
                check_type="text",
                search_keyword="保險金",
                status=CheckStatus.PENDING,
            )
        ],
    )

    with TestClient(app) as client:
        review_response = client.post(
            f"/api/review/{comparison_id}/confirm",
            headers=_auth_headers(reviewer),
            json={"diff_item_id": "d001", "action": "confirmed"},
        )
        assert review_response.status_code == 200

        response = client.post(
            f"/api/archive/{comparison_id}/verify",
            headers=_auth_headers(reviewer),
            json={},
        )

    assert response.status_code == 409
    assert "Checklist" in response.json()["detail"]


def test_upload_rejects_pdf_extension_with_non_pdf_content(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    reviewer = create_user("carol", "陳審核", "secret")

    with TestClient(app) as client:
        response = client.post(
            "/api/compare/upload",
            headers=_auth_headers(reviewer),
            files={
                "old_pdf": ("old.pdf", b"not a real pdf", "application/pdf"),
                "new_pdf": ("new.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf"),
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid PDF file: old.pdf"


def test_download_token_is_bound_to_allowed_path(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    reviewer = create_user("download-user", "下載人員", "secret")

    with TestClient(app) as client:
        issue = client.post(
            "/api/auth/download-token",
            headers=_auth_headers(reviewer),
            json={"path": "/api/projects/all/comparisons/export"},
        )
        assert issue.status_code == 200
        token = issue.json()["token"]

        ok_response = client.get(
            f"/api/projects/all/comparisons/export?download_token={token}"
        )
        wrong_path_response = client.get(
            f"/api/projects/all/comparisons?download_token={token}"
        )

    assert ok_response.status_code == 200
    assert wrong_path_response.status_code == 401


def test_download_token_rejects_disallowed_path(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    reviewer = create_user("bad-download-user", "下載人員", "secret")

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/download-token",
            headers=_auth_headers(reviewer),
            json={"path": "/api/auth/users"},
        )

    assert response.status_code == 400


def test_download_token_rejects_non_resource_compare_path(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    reviewer = create_user("upload-token-user", "票證測試", "secret")

    with TestClient(app) as client:
        response = client.post(
            "/api/auth/download-token",
            headers=_auth_headers(reviewer),
            json={"path": "/api/compare/upload"},
        )

    assert response.status_code == 400


def test_download_token_allows_compare_pdf_resource_path(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    _seed_done_comparison("cmp-pdf-token", tmp_path)
    reviewer = create_user("pdf-token-user", "PDF 票證", "secret")

    with TestClient(app) as client:
        issue = client.post(
            "/api/auth/download-token",
            headers=_auth_headers(reviewer),
            json={"path": "/api/compare/cmp-pdf-token/pdf/old"},
        )
        assert issue.status_code == 200

        response = client.get(
            f"/api/compare/cmp-pdf-token/pdf/old?download_token={issue.json()['token']}"
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"


def test_download_token_allows_websocket_resource_path(monkeypatch, tmp_path: Path):
    _prepare_temp_app(monkeypatch, tmp_path)
    init_db()
    reviewer = create_user("ws-token-user", "WS 票證", "secret")

    with TestClient(app) as client:
        issue = client.post(
            "/api/auth/download-token",
            headers=_auth_headers(reviewer),
            json={"path": "/ws/compare/cmp-ws-token"},
        )

    assert issue.status_code == 200
    assert issue.json()["expires_in"] == 120
