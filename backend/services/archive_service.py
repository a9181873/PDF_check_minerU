import hashlib
import shutil
import uuid
from pathlib import Path

from config import settings
from models.database import (
    create_pdf_archive,
    create_verification_session,
    get_archive_by_hashes,
    get_review_counts,
    update_archive_annotated_path,
    update_comparison_hashes,
)
from models.diff_models import DiffReport
from services.export_service import export_annotated_pdf


def compute_pdf_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_pdf_path(upload_dir: Path, task_id: str) -> Path | None:
    candidates = list(upload_dir.glob(f"{task_id}_*.pdf"))
    return candidates[0] if candidates else None


def ensure_comparison_hashes(comparison_id: str, old_path: Path, new_path: Path) -> tuple[str, str]:
    old_hash = compute_pdf_hash(old_path)
    new_hash = compute_pdf_hash(new_path)
    update_comparison_hashes(comparison_id, old_hash, new_hash)
    return old_hash, new_hash


def archive_comparison(
    comparison_id: str,
    report: DiffReport,
    old_path: Path,
    new_path: Path,
    old_hash: str,
    new_hash: str,
) -> tuple[dict, bool]:
    """
    Returns (archive_record, is_new_archive).
    If an archive with the same (old_hash, new_hash) already exists, returns it directly.
    Otherwise creates a new archive entry with copied files.
    """
    existing = get_archive_by_hashes(old_hash, new_hash)
    if existing:
        return existing, False

    archive_id = str(uuid.uuid4())
    dest_dir = settings.archive_dir / archive_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    old_dest = dest_dir / f"old_{old_path.name}"
    new_dest = dest_dir / f"new_{new_path.name}"
    shutil.copy2(old_path, old_dest)
    shutil.copy2(new_path, new_dest)

    annotated_dest = dest_dir / "annotated.pdf"
    try:
        export_annotated_pdf(str(new_path), report.items, str(annotated_dest))
        annotated_path = str(annotated_dest)
    except Exception:
        annotated_path = None

    record = create_pdf_archive(
        archive_id=archive_id,
        old_hash=old_hash,
        new_hash=new_hash,
        old_filename=getattr(report, "old_filename", old_path.name),
        new_filename=getattr(report, "new_filename", new_path.name),
        old_archive_path=str(old_dest),
        new_archive_path=str(new_dest),
        annotated_archive_path=annotated_path,
        first_comparison_id=comparison_id,
    )
    return record, True


def record_verification(
    archive_id: str,
    comparison_id: str,
    reviewer: str | None,
    report: DiffReport,
    notes: str | None,
) -> dict:
    counts = get_review_counts(comparison_id)
    total = len(report.items)
    session_id = str(uuid.uuid4())
    return create_verification_session(
        session_id=session_id,
        archive_id=archive_id,
        comparison_id=comparison_id,
        reviewer=reviewer,
        total_diffs=total,
        confirmed=counts.get("confirmed", 0),
        flagged=counts.get("flagged", 0),
        notes=notes,
    )
