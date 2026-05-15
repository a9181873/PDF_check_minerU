import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from models.diff_models import ChecklistItem, DiffReport

DEFAULT_PROJECT_ID = "default"
DEFAULT_PROJECT_NAME = "Default Project"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection(db_path: Path | None = None):
    path = db_path or settings.db_path
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    names = {row[1] for row in columns}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _create_pdf_archives_table_sql(table_name: str = "pdf_archives") -> str:
    return f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id TEXT PRIMARY KEY,
                old_hash TEXT NOT NULL,
                new_hash TEXT NOT NULL,
                case_number TEXT,
                old_filename TEXT NOT NULL,
                new_filename TEXT NOT NULL,
                old_archive_path TEXT NOT NULL,
                new_archive_path TEXT NOT NULL,
                annotated_archive_path TEXT,
                first_comparison_id TEXT NOT NULL,
                archived_at TEXT NOT NULL
            );
            """


def _has_hash_only_archive_unique_constraint(conn: sqlite3.Connection) -> bool:
    indexes = conn.execute("PRAGMA index_list(pdf_archives)").fetchall()
    for index in indexes:
        if not index["unique"]:
            continue
        cols = conn.execute(f"PRAGMA index_info({index['name']})").fetchall()
        names = [col["name"] for col in cols]
        if names == ["old_hash", "new_hash"]:
            return True
    return False


def _migrate_pdf_archives_case_number_uniqueness(conn: sqlite3.Connection) -> None:
    if not _has_hash_only_archive_unique_constraint(conn):
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("ALTER TABLE pdf_archives RENAME TO pdf_archives_old")
    conn.executescript(_create_pdf_archives_table_sql("pdf_archives"))
    conn.execute(
        """
        INSERT INTO pdf_archives (
            id, old_hash, new_hash, case_number, old_filename, new_filename,
            old_archive_path, new_archive_path, annotated_archive_path,
            first_comparison_id, archived_at
        )
        SELECT
            id, old_hash, new_hash, case_number, old_filename, new_filename,
            old_archive_path, new_archive_path, annotated_archive_path,
            first_comparison_id, archived_at
        FROM pdf_archives_old
        """
    )
    conn.execute("DROP TABLE pdf_archives_old")
    conn.execute("PRAGMA foreign_keys=ON")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS comparisons (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                case_number TEXT,
                old_filename TEXT NOT NULL,
                new_filename TEXT NOT NULL,
                old_file_path TEXT NOT NULL,
                new_file_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                diff_result_json TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );

            CREATE TABLE IF NOT EXISTS review_logs (
                id TEXT PRIMARY KEY,
                comparison_id TEXT NOT NULL,
                diff_item_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reviewer TEXT,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (comparison_id) REFERENCES comparisons(id)
            );

            CREATE TABLE IF NOT EXISTS checklists (
                id TEXT PRIMARY KEY,
                comparison_id TEXT NOT NULL,
                items_json TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                FOREIGN KEY (comparison_id) REFERENCES comparisons(id)
            );

            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'reviewer',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS resource_logs (
                task_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                elapsed_seconds REAL,
                peak_memory_mb REAL,
                avg_cpu_percent REAL,
                peak_cpu_percent REAL,
                old_filename TEXT,
                new_filename TEXT,
                total_diffs INTEGER,
                system_info_json TEXT,
                snapshots_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS verification_sessions (
                id TEXT PRIMARY KEY,
                archive_id TEXT NOT NULL,
                comparison_id TEXT NOT NULL,
                case_number TEXT,
                reviewer TEXT,
                verified_at TEXT NOT NULL,
                total_diffs INTEGER,
                confirmed INTEGER,
                flagged INTEGER,
                notes TEXT,
                review_logs_json TEXT,
                FOREIGN KEY (archive_id) REFERENCES pdf_archives(id)
            );
            """
        )
        conn.executescript(_create_pdf_archives_table_sql())
        _ensure_column(conn, "comparisons", "case_number", "TEXT")
        _ensure_column(conn, "comparisons", "error_message", "TEXT")
        _ensure_column(conn, "comparisons", "old_markdown_path", "TEXT")
        _ensure_column(conn, "comparisons", "new_markdown_path", "TEXT")
        _ensure_column(conn, "comparisons", "snapshot_dir", "TEXT")
        _ensure_column(conn, "comparisons", "old_hash", "TEXT")
        _ensure_column(conn, "comparisons", "new_hash", "TEXT")
        _ensure_column(conn, "pdf_archives", "case_number", "TEXT")
        _ensure_column(conn, "verification_sessions", "case_number", "TEXT")
        _ensure_column(conn, "verification_sessions", "review_logs_json", "TEXT")
        _migrate_pdf_archives_case_number_uniqueness(conn)
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_pdf_archives_hash_case
            ON pdf_archives(old_hash, new_hash, COALESCE(case_number, ''))
            """
        )


def create_project(name: str) -> dict[str, str]:
    now = utc_now_iso()
    project_id = str(uuid.uuid4())
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (project_id, name, now, now),
        )
    return {"id": project_id, "name": name, "created_at": now, "updated_at": now}


def project_exists(project_id: str) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
    return bool(row)


def ensure_default_project() -> str:
    now = utc_now_iso()
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (DEFAULT_PROJECT_ID,)).fetchone()
        if row:
            return DEFAULT_PROJECT_ID
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (DEFAULT_PROJECT_ID, DEFAULT_PROJECT_NAME, now, now),
        )
    return DEFAULT_PROJECT_ID


def list_projects() -> list[dict[str, str]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, updated_at FROM projects ORDER BY created_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def create_comparison(
    comparison_id: str,
    project_id: str,
    old_filename: str,
    new_filename: str,
    old_file_path: str,
    new_file_path: str,
    case_number: str | None = None,
) -> None:
    now = utc_now_iso()
    normalized_case_number = case_number.strip() if case_number else None
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO comparisons (
                id, project_id, case_number, old_filename, new_filename,
                old_file_path, new_file_path, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                comparison_id,
                project_id,
                normalized_case_number,
                old_filename,
                new_filename,
                old_file_path,
                new_file_path,
                "pending",
                now,
            ),
        )


def update_comparison_status(
    comparison_id: str,
    status: str,
    *,
    error_message: str | None = None,
    completed: bool = False,
) -> None:
    with get_connection() as conn:
        completed_at = utc_now_iso() if completed else None
        conn.execute(
            """
            UPDATE comparisons
            SET status = ?, error_message = ?, completed_at = COALESCE(?, completed_at)
            WHERE id = ?
            """,
            (status, error_message, completed_at, comparison_id),
        )


def save_diff_report(comparison_id: str, report: DiffReport) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE comparisons
            SET status = 'done',
                diff_result_json = ?,
                error_message = NULL,
                completed_at = ?
            WHERE id = ?
            """,
            (report.model_dump_json(), utc_now_iso(), comparison_id),
        )


def save_comparison_report_state(comparison_id: str, report: DiffReport) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE comparisons
            SET diff_result_json = ?
            WHERE id = ?
            """,
            (report.model_dump_json(), comparison_id),
        )


def save_markdown_paths(
    comparison_id: str,
    *,
    old_markdown_path: str | None,
    new_markdown_path: str | None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE comparisons
            SET old_markdown_path = ?, new_markdown_path = ?
            WHERE id = ?
            """,
            (old_markdown_path, new_markdown_path, comparison_id),
        )


def get_markdown_paths(comparison_id: str) -> dict[str, str | None] | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT old_markdown_path, new_markdown_path FROM comparisons WHERE id = ?",
            (comparison_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "old_markdown_path": row["old_markdown_path"],
        "new_markdown_path": row["new_markdown_path"],
    }


def save_comparison_error(comparison_id: str, error_message: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE comparisons
            SET status = 'error',
                error_message = ?,
                completed_at = ?
            WHERE id = ?
            """,
            (error_message, utc_now_iso(), comparison_id),
        )


def get_comparison(comparison_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM comparisons WHERE id = ?", (comparison_id,)).fetchone()
    return dict(row) if row else None


def get_comparison_report(comparison_id: str) -> DiffReport | None:
    row = get_comparison(comparison_id)
    if not row or not row.get("diff_result_json"):
        return None
    payload = row["diff_result_json"]
    if isinstance(payload, str):
        data = json.loads(payload)
    else:
        data = payload
    return DiffReport.model_validate(data)


def list_project_comparisons(project_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, case_number, old_filename, new_filename, status,
                   created_at, completed_at, error_message,
                   old_markdown_path, new_markdown_path,
                   (
                       SELECT reviewer
                       FROM verification_sessions
                       WHERE verification_sessions.comparison_id = comparisons.id
                       ORDER BY verified_at DESC, rowid DESC
                       LIMIT 1
                   ) AS latest_reviewer,
                   (
                       SELECT verified_at
                       FROM verification_sessions
                       WHERE verification_sessions.comparison_id = comparisons.id
                       ORDER BY verified_at DESC, rowid DESC
                       LIMIT 1
                   ) AS latest_verified_at
            FROM comparisons
            WHERE project_id = ?
            ORDER BY created_at DESC
            """,
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_all_comparisons(limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, case_number, old_filename, new_filename, status,
                   created_at, completed_at, error_message,
                   old_markdown_path, new_markdown_path,
                   (
                       SELECT reviewer
                       FROM verification_sessions
                       WHERE verification_sessions.comparison_id = comparisons.id
                       ORDER BY verified_at DESC, rowid DESC
                       LIMIT 1
                   ) AS latest_reviewer,
                   (
                       SELECT verified_at
                       FROM verification_sessions
                       WHERE verification_sessions.comparison_id = comparisons.id
                       ORDER BY verified_at DESC, rowid DESC
                       LIMIT 1
                   ) AS latest_verified_at
            FROM comparisons
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def delete_comparison(comparison_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM comparisons WHERE id = ?", (comparison_id,))
    return cursor.rowcount > 0


def list_all_comparisons_unlimited() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, project_id, case_number, old_filename, new_filename, status,
                   created_at, completed_at, error_message,
                   (
                       SELECT reviewer
                       FROM verification_sessions
                       WHERE verification_sessions.comparison_id = comparisons.id
                       ORDER BY verified_at DESC, rowid DESC
                       LIMIT 1
                   ) AS latest_reviewer
            FROM comparisons
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def add_review_log(
    comparison_id: str,
    diff_item_id: str,
    action: str,
    reviewer: str | None,
    note: str | None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO review_logs (
                id, comparison_id, diff_item_id, action, reviewer, note, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                comparison_id,
                diff_item_id,
                action,
                reviewer,
                note,
                utc_now_iso(),
            ),
        )


def get_latest_review_actions(comparison_id: str) -> dict[str, str]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT diff_item_id, action
            FROM review_logs
            WHERE comparison_id = ?
            ORDER BY created_at DESC, rowid DESC
            """,
            (comparison_id,),
        ).fetchall()

    latest: dict[str, str] = {}
    for row in rows:
        diff_item_id = row["diff_item_id"]
        if diff_item_id not in latest:
            latest[diff_item_id] = row["action"]
    return latest


def get_review_counts(comparison_id: str) -> dict[str, int]:
    latest = get_latest_review_actions(comparison_id)
    counts = {"confirmed": 0, "flagged": 0, "skipped": 0}
    for action in latest.values():
        if action in counts:
            counts[action] += 1
    return counts


def get_review_logs(comparison_id: str) -> list[dict[str, str | None]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, comparison_id, diff_item_id, action, reviewer, note, created_at
            FROM review_logs
            WHERE comparison_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (comparison_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _describe_review_change(
    current: dict[str, str | None],
    previous: dict[str, str | None] | None,
) -> str:
    def fmt(value: str | None) -> str:
        return value if value not in (None, "") else "空白"

    if previous is None:
        return (
            f"建立審核紀錄：狀態 {fmt(current.get('action'))}，"
            f"審核人員 {fmt(current.get('reviewer'))}，備註 {fmt(current.get('note'))}"
        )

    changes: list[str] = []
    for key, label in (("action", "狀態"), ("reviewer", "審核人員"), ("note", "備註")):
        old = previous.get(key)
        new = current.get(key)
        if old != new:
            changes.append(f"{label}由「{fmt(old)}」改為「{fmt(new)}」")
    return "；".join(changes) if changes else "重複儲存，內容未變更"


def get_review_logs_with_changes(comparison_id: str) -> list[dict[str, str | None]]:
    logs = get_review_logs(comparison_id)
    latest_by_diff: dict[str, dict[str, str | None]] = {}
    enriched: list[dict[str, str | None]] = []

    for log in logs:
        diff_item_id = log.get("diff_item_id") or ""
        previous = latest_by_diff.get(diff_item_id)
        item = dict(log)
        item["previous_action"] = previous.get("action") if previous else None
        item["previous_reviewer"] = previous.get("reviewer") if previous else None
        item["previous_note"] = previous.get("note") if previous else None
        item["change_type"] = "modified" if previous else "created"
        item["change_summary"] = _describe_review_change(item, previous)
        enriched.append(item)
        latest_by_diff[diff_item_id] = log

    return enriched


def save_checklist(comparison_id: str, items: list[ChecklistItem]) -> None:
    payload = json.dumps([item.model_dump(mode="json") for item in items], ensure_ascii=False)
    imported_at = utc_now_iso()
    checklist_id = str(uuid.uuid4())
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM checklists WHERE comparison_id = ?",
            (comparison_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE checklists
                SET items_json = ?, imported_at = ?
                WHERE comparison_id = ?
                """,
                (payload, imported_at, comparison_id),
            )
            return

        conn.execute(
            """
            INSERT INTO checklists (id, comparison_id, items_json, imported_at)
            VALUES (?, ?, ?, ?)
            """,
            (checklist_id, comparison_id, payload, imported_at),
        )


def get_checklist(comparison_id: str) -> list[ChecklistItem]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT items_json FROM checklists WHERE comparison_id = ?",
            (comparison_id,),
        ).fetchone()
    if not row:
        return []
    payload = json.loads(row["items_json"])
    return [ChecklistItem.model_validate(item) for item in payload]


def save_snapshot_dir(comparison_id: str, snapshot_dir: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE comparisons SET snapshot_dir = ? WHERE id = ?",
            (snapshot_dir, comparison_id),
        )


def get_snapshot_dir(comparison_id: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT snapshot_dir FROM comparisons WHERE id = ?",
            (comparison_id,),
        ).fetchone()
    if not row:
        return None
    return row["snapshot_dir"]


# ── User management ──────────────────────────────────────────────────────────

import hashlib
import secrets


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return (hash_hex, salt_hex)."""
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return h.hex(), salt


def _make_password_hash(password: str) -> str:
    """Encode as 'salt$hash'."""
    hash_hex, salt = _hash_password(password)
    return f"{salt}${hash_hex}"


def verify_password(password: str, stored_hash: str) -> bool:
    parts = stored_hash.split("$", 1)
    if len(parts) != 2:
        return False
    salt, expected = parts
    h, _ = _hash_password(password, salt)
    return secrets.compare_digest(h, expected)


def create_user(
    username: str, display_name: str, password: str, role: str = "reviewer"
) -> dict:
    now = utc_now_iso()
    user_id = str(uuid.uuid4())
    pw_hash = _make_password_hash(password)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO users (id, username, display_name, password_hash, role, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (user_id, username, display_name, pw_hash, role, now, now),
        )
    return {"id": user_id, "username": username, "display_name": display_name, "role": role, "is_active": True, "created_at": now}


def get_user_by_username(username: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at, updated_at FROM users ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_user(user_id: str, *, display_name: str | None = None, password: str | None = None, role: str | None = None, is_active: bool | None = None) -> bool:
    sets: list[str] = []
    params: list = []
    if display_name is not None:
        sets.append("display_name = ?"); params.append(display_name)
    if password is not None:
        sets.append("password_hash = ?"); params.append(_make_password_hash(password))
    if role is not None:
        sets.append("role = ?"); params.append(role)
    if is_active is not None:
        sets.append("is_active = ?"); params.append(int(is_active))
    if not sets:
        return False
    sets.append("updated_at = ?"); params.append(utc_now_iso())
    params.append(user_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)
    return True


def delete_user(user_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cur.rowcount > 0


def update_comparison_hashes(comparison_id: str, old_hash: str, new_hash: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE comparisons SET old_hash = ?, new_hash = ? WHERE id = ?",
            (old_hash, new_hash, comparison_id),
        )


def get_archive_by_hashes(old_hash: str, new_hash: str, case_number: str | None = None) -> dict | None:
    normalized_case_number = case_number.strip() if case_number else ""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM pdf_archives
            WHERE old_hash = ?
              AND new_hash = ?
              AND COALESCE(case_number, '') = ?
            """,
            (old_hash, new_hash, normalized_case_number),
        ).fetchone()
    return dict(row) if row else None


def create_pdf_archive(
    archive_id: str,
    old_hash: str,
    new_hash: str,
    case_number: str | None,
    old_filename: str,
    new_filename: str,
    old_archive_path: str,
    new_archive_path: str,
    annotated_archive_path: str | None,
    first_comparison_id: str,
) -> dict:
    now = utc_now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO pdf_archives
               (id, old_hash, new_hash, case_number, old_filename, new_filename,
                old_archive_path, new_archive_path, annotated_archive_path,
                first_comparison_id, archived_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (archive_id, old_hash, new_hash, case_number, old_filename, new_filename,
             old_archive_path, new_archive_path, annotated_archive_path,
             first_comparison_id, now),
        )
    return {
        "id": archive_id, "old_hash": old_hash, "new_hash": new_hash,
        "case_number": case_number,
        "old_filename": old_filename, "new_filename": new_filename,
        "old_archive_path": old_archive_path, "new_archive_path": new_archive_path,
        "annotated_archive_path": annotated_archive_path,
        "first_comparison_id": first_comparison_id, "archived_at": now,
    }


def update_archive_annotated_path(archive_id: str, annotated_path: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE pdf_archives SET annotated_archive_path = ? WHERE id = ?",
            (annotated_path, archive_id),
        )


def create_verification_session(
    session_id: str,
    archive_id: str,
    comparison_id: str,
    case_number: str | None,
    reviewer: str | None,
    total_diffs: int,
    confirmed: int,
    flagged: int,
    notes: str | None,
    review_logs: list[dict[str, str | None]] | None = None,
) -> dict:
    now = utc_now_iso()
    review_logs_json = json.dumps(review_logs or [], ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO verification_sessions
               (id, archive_id, comparison_id, case_number, reviewer, verified_at,
                total_diffs, confirmed, flagged, notes, review_logs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, archive_id, comparison_id, case_number, reviewer, now,
             total_diffs, confirmed, flagged, notes, review_logs_json),
        )
    return {
        "id": session_id, "archive_id": archive_id, "comparison_id": comparison_id,
        "case_number": case_number,
        "reviewer": reviewer, "verified_at": now, "total_diffs": total_diffs,
        "confirmed": confirmed, "flagged": flagged, "notes": notes,
        "review_logs_json": review_logs_json,
    }


def get_verification_sessions_by_archive(archive_id: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM verification_sessions WHERE archive_id = ? ORDER BY verified_at DESC",
            (archive_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_archive_by_comparison(comparison_id: str) -> dict | None:
    with get_connection() as conn:
        comp = conn.execute(
            "SELECT old_hash, new_hash, case_number FROM comparisons WHERE id = ?",
            (comparison_id,),
        ).fetchone()
        if not comp or not comp["old_hash"]:
            return None
        row = conn.execute(
            """
            SELECT * FROM pdf_archives
            WHERE old_hash = ?
              AND new_hash = ?
              AND COALESCE(case_number, '') = ?
            """,
            (comp["old_hash"], comp["new_hash"], (comp["case_number"] or "").strip()),
        ).fetchone()
    return dict(row) if row else None


def ensure_default_admin() -> None:
    """Create default admin account if no users exist.

    Password resolution order:
    1. Env var DEFAULT_ADMIN_PASSWORD if set
    2. Auto-generated random password written to runtime/.initial_admin_password
       (file is chmod 600; admin should read it once then delete)
    """
    import logging
    import os
    import secrets
    from config import settings as _settings

    with get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count != 0:
        return

    password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "").strip()
    if not password:
        password = secrets.token_urlsafe(16)
        try:
            pw_file = _settings.data_dir / ".initial_admin_password"
            pw_file.write_text(password + "\n")
            pw_file.chmod(0o600)
            logging.warning(
                "Default admin created. Initial password written to %s — read it and delete the file.",
                pw_file,
            )
        except OSError:
            logging.warning("Default admin initial password (save now): %s", password)
    create_user("admin", "系統管理員", password, role="admin")
