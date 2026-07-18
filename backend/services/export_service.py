import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from models.diff_models import CheckStatus, ChecklistItem, DiffItem, DiffReport, DiffType
from services.pymupdf_guard import pymupdf_serialized

_DIFF_COLORS = {
    DiffType.NUMBER_MODIFIED: (1.0, 0.5, 0.0),
    DiffType.TEXT_MODIFIED: (1.0, 0.7, 0.0),
    DiffType.ADDED: (0.0, 0.7, 0.0),
    DiffType.DELETED: (0.8, 0.0, 0.0),
}


@pymupdf_serialized
def _pdf_rect_from_bbox(page, bbox):
    import fitz

    y0_top = page.rect.height - bbox.y1
    y1_top = page.rect.height - bbox.y0
    return fitz.Rect(bbox.x0, y0_top, bbox.x1, y1_top)


@pymupdf_serialized
def export_annotated_pdf(new_pdf_path: str, diff_items: list[DiffItem], output_path: str) -> str:
    try:
        import fitz
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependency
        raise RuntimeError(
            "PyMuPDF is required for PDF export. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(new_pdf_path) as doc:
        for item in diff_items:
            bbox = item.new_bbox or item.old_bbox
            if not bbox:
                continue
            page = doc[bbox.page - 1]
            rect = _pdf_rect_from_bbox(page, bbox)
            color = _DIFF_COLORS[item.diff_type]

            page.draw_rect(rect, color=color, width=1.5, fill=color, fill_opacity=0.12)
            note = f"{item.diff_type.value}: {item.old_value or '-'} -> {item.new_value or '-'}"
            page.add_highlight_annot(rect).set_info(content=note)

        doc.save(output)

    return str(output)


def export_review_excel(
    comparison_id: str,
    diff_report: DiffReport,
    checklist: list[ChecklistItem] | None,
    review_counts: dict[str, int] | None,
    output_path: str,
) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    review_counts = review_counts or {}

    diff_rows = []
    for item in diff_report.items:
        bbox = item.new_bbox or item.old_bbox
        diff_rows.append(
            {
                "id": item.id,
                "type": item.diff_type.value,
                "old_value": item.old_value,
                "new_value": item.new_value,
                "page": bbox.page if bbox else None,
                "context": item.context,
                "reviewed": item.reviewed,
                "reviewed_by": item.reviewed_by,
                "reviewed_at": item.reviewed_at,
            }
        )

    checklist_rows = []
    if checklist:
        for item in checklist:
            checklist_rows.append(
                {
                    "item_id": item.item_id,
                    "check_type": item.check_type,
                    "keyword": item.search_keyword,
                    "expected_old": item.expected_old,
                    "expected_new": item.expected_new,
                    "status": item.status.value,
                    "matched_diff_id": item.matched_diff_id,
                    "note": item.note,
                }
            )

    total = len(diff_report.items)
    confirmed = review_counts.get("confirmed", sum(1 for d in diff_report.items if d.reviewed))
    flagged = review_counts.get("flagged", 0)
    reviewed = confirmed + flagged
    summary_df = pd.DataFrame(
        [
            {
                "comparison_id": comparison_id,
                "total": total,
                "confirmed": confirmed,
                "flagged": flagged,
                "pending": max(total - reviewed, 0),
                "checklist_confirmed": sum(
                    1 for c in checklist or [] if c.status == CheckStatus.CONFIRMED
                ),
            }
        ]
    )

    with pd.ExcelWriter(output) as writer:
        pd.DataFrame(diff_rows).to_excel(writer, index=False, sheet_name="diffs")
        pd.DataFrame(checklist_rows).to_excel(writer, index=False, sheet_name="checklist")
        summary_df.to_excel(writer, index=False, sheet_name="summary")

    return str(output)


@pymupdf_serialized
def export_review_report_pdf(
    comparison_id: str,
    diff_report: DiffReport,
    checklist: list[ChecklistItem] | None,
    review_counts: dict[str, int] | None,
    output_path: str,
) -> str:
    try:
        import fitz
    except ModuleNotFoundError as exc:  # pragma: no cover - environment dependency
        raise RuntimeError(
            "PyMuPDF is required for PDF export. Install dependencies with: pip install -r requirements.txt"
        ) from exc

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    checklist = checklist or []
    review_counts = review_counts or {}
    total = len(diff_report.items)
    confirmed = review_counts.get("confirmed", 0)
    flagged = review_counts.get("flagged", 0)
    reviewed = confirmed + flagged
    summary_lines = [
        "PDF Check Review Report",
        "",
        f"Comparison ID: {comparison_id}",
        f"Old file: {diff_report.old_filename}",
        f"New file: {diff_report.new_filename}",
        f"Created at: {diff_report.created_at}",
        "",
        "Diff Summary",
        f"- Total diffs: {total}",
        f"- Confirmed diffs: {confirmed}",
        f"- Flagged diffs: {flagged}",
        f"- Reviewed diffs: {reviewed}",
        f"- Pending diffs: {max(total - reviewed, 0)}",
        f"- Added: {sum(1 for item in diff_report.items if item.diff_type == DiffType.ADDED)}",
        f"- Deleted: {sum(1 for item in diff_report.items if item.diff_type == DiffType.DELETED)}",
        f"- Modified: {sum(1 for item in diff_report.items if item.diff_type in {DiffType.TEXT_MODIFIED, DiffType.NUMBER_MODIFIED})}",
        "",
        "Checklist Summary",
        f"- Total checklist items: {len(checklist)}",
        f"- Confirmed: {sum(1 for item in checklist if item.status == CheckStatus.CONFIRMED)}",
        f"- Anomaly: {sum(1 for item in checklist if item.status == CheckStatus.ANOMALY)}",
        f"- Missing: {sum(1 for item in checklist if item.status == CheckStatus.MISSING)}",
        f"- Pending: {sum(1 for item in checklist if item.status == CheckStatus.PENDING)}",
        "",
        "Top Diff Items",
    ]

    diff_lines: list[str] = []
    for index, item in enumerate(diff_report.items, start=1):
        diff_lines.append(
            f"{index}. [{item.diff_type.value}] {item.context} | old={item.old_value or '-'} | new={item.new_value or '-'}"
        )

    checklist_lines = ["", "Checklist Details"]
    for index, item in enumerate(checklist, start=1):
        checklist_lines.append(
            f"{index}. [{item.status.value}] {item.item_id} {item.search_keyword} -> matched={item.matched_diff_id or '-'}"
        )

    doc = fitz.open()
    page = doc.new_page()
    rect = fitz.Rect(48, 48, page.rect.width - 48, page.rect.height - 48)
    all_lines = summary_lines + diff_lines + checklist_lines

    current_page = page
    current_rect = rect
    current_y = current_rect.y0
    line_height = 18

    for line in all_lines:
        if current_y + line_height > current_rect.y1:
            current_page = doc.new_page()
            current_rect = fitz.Rect(48, 48, current_page.rect.width - 48, current_page.rect.height - 48)
            current_y = current_rect.y0
        current_page.insert_text(
            fitz.Point(current_rect.x0, current_y),
            line,
            fontsize=11,
            fontname="china-t",
        )
        current_y += line_height

    doc.save(output)
    doc.close()
    return str(output)


def export_review_log_json(
    comparison_id: str,
    diff_report: DiffReport,
    checklist: list[ChecklistItem] | None,
    review_counts: dict[str, int] | None,
    review_logs: list[dict[str, str | None]] | None,
    output_path: str,
) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    checklist = checklist or []
    review_counts = review_counts or {}
    review_logs = review_logs or []
    total = len(diff_report.items)
    confirmed = review_counts.get("confirmed", 0)
    flagged = review_counts.get("flagged", 0)
    reviewed = confirmed + flagged

    payload = {
        "comparison_id": comparison_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "old_filename": diff_report.old_filename,
        "new_filename": diff_report.new_filename,
        "created_at": diff_report.created_at,
        "summary": diff_report.summary,
        "diff_summary": {
            "total": total,
            "confirmed": confirmed,
            "flagged": flagged,
            "pending": max(total - reviewed, 0),
            "added": sum(1 for item in diff_report.items if item.diff_type == DiffType.ADDED),
            "deleted": sum(1 for item in diff_report.items if item.diff_type == DiffType.DELETED),
            "modified": sum(
                1
                for item in diff_report.items
                if item.diff_type in {DiffType.TEXT_MODIFIED, DiffType.NUMBER_MODIFIED}
            ),
        },
        "checklist_summary": {
            "total": len(checklist),
            "confirmed": sum(1 for item in checklist if item.status == CheckStatus.CONFIRMED),
            "anomaly": sum(1 for item in checklist if item.status == CheckStatus.ANOMALY),
            "missing": sum(1 for item in checklist if item.status == CheckStatus.MISSING),
            "pending": sum(1 for item in checklist if item.status == CheckStatus.PENDING),
        },
        "diff_items": [item.model_dump(mode="json") for item in diff_report.items],
        "checklist_items": [item.model_dump(mode="json") for item in checklist],
        "review_logs": review_logs,
    }

    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(output)


def _diff_type_label(dt: DiffType) -> str:
    labels = {
        DiffType.NUMBER_MODIFIED: "數值修改",
        DiffType.TEXT_MODIFIED: "文字修改",
        DiffType.ADDED: "新增內容",
        DiffType.DELETED: "刪除內容",
    }
    return labels.get(dt, str(dt.value))


def _truncate(text: str | None, length: int = 20) -> str:
    if not text:
        return "-"
    text = text.replace("\n", " ").replace("\r", "")
    if len(text) > length:
        return text[:length - 1] + "…"
    return text


def export_review_log_txt(
    comparison_id: str,
    diff_report: DiffReport,
    checklist: list[ChecklistItem] | None,
    review_counts: dict[str, int] | None,
    review_logs: list[dict[str, str | None]] | None,
    output_path: str,
) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    checklist = checklist or []
    review_counts = review_counts or {}
    review_logs = review_logs or []
    total = len(diff_report.items)
    confirmed = review_counts.get("confirmed", 0)
    flagged = review_counts.get("flagged", 0)
    reviewed = confirmed + flagged
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    created_at = diff_report.created_at.replace("T", " ").split(".")[0] if diff_report.created_at else "-"

    lines: list[str] = []
    sep = "═" * 56
    lines.append(sep)
    lines.append("  PDF 差異比對 — 審核檢視紀錄")
    lines.append(sep)
    lines.append("")

    # Basic info
    lines.append("■ 基本資訊")
    lines.append(f"  比對 ID:    {comparison_id}")
    lines.append(f"  舊版檔案:   {diff_report.old_filename}")
    lines.append(f"  新版檔案:   {diff_report.new_filename}")
    lines.append(f"  建立時間:   {created_at}")
    lines.append(f"  匯出時間:   {exported_at}")
    lines.append("")

    # Summary
    lines.append("■ 差異摘要")
    lines.append(f"  總差異數:   {total}")
    lines.append(f"  已確認:     {confirmed}")
    lines.append(f"  已標記:     {flagged}")
    lines.append(f"  待審核:     {max(total - reviewed, 0)}")
    added = sum(1 for item in diff_report.items if item.diff_type == DiffType.ADDED)
    deleted = sum(1 for item in diff_report.items if item.diff_type == DiffType.DELETED)
    modified = sum(
        1 for item in diff_report.items
        if item.diff_type in {DiffType.TEXT_MODIFIED, DiffType.NUMBER_MODIFIED}
    )
    lines.append(f"  新增:       {added}")
    lines.append(f"  刪除:       {deleted}")
    lines.append(f"  修改:       {modified}")
    lines.append("")

    # Diff detail table
    lines.append("■ 差異明細")
    # Column widths: #=5, type=10, old=20, new=20, status=10, reviewer=10
    header = f"  {'#':<5}{'類型':<10}{'原始內容':<22}{'修訂內容':<22}{'審核狀態':<10}{'審核人員':<10}"
    lines.append("  " + "-" * 79)
    lines.append(header)
    lines.append("  " + "-" * 79)
    for idx, item in enumerate(diff_report.items, start=1):
        dtype = _diff_type_label(item.diff_type)
        old_val = _truncate(item.old_value, 20)
        new_val = _truncate(item.new_value, 20)
        status = "已審核" if item.reviewed else "待審核"
        reviewer = _truncate(item.reviewed_by, 10) if item.reviewed_by else "-"
        lines.append(f"  {idx:<5}{dtype:<10}{old_val:<22}{new_val:<22}{status:<10}{reviewer:<10}")
    lines.append("  " + "-" * 79)
    lines.append("")

    # Review operation logs
    if review_logs:
        lines.append("■ 審核操作紀錄")
        diff_by_id = {item.id: item for item in diff_report.items}
        for idx, log in enumerate(review_logs, start=1):
            log_time = (log.get("created_at") or "-").replace("T", " ").split(".")[0]
            reviewer_name = log.get("reviewer") or "匿名"
            action = "確認" if log.get("action") == "confirmed" else "標記問題" if log.get("action") == "flagged" else str(log.get("action", "-"))
            diff_id = log.get("diff_item_id", "-")
            diff_item = diff_by_id.get(diff_id or "")
            context = f" ({diff_item.context})" if diff_item and diff_item.context else ""
            note_text = f" (備註: {log.get('note')})" if log.get("note") else ""
            lines.append(f"  {idx}. [{log_time}] {reviewer_name} → {action} {diff_id}{context}{note_text}")
        lines.append("")

    # Checklist summary if present
    if checklist:
        lines.append("■ 核對清單摘要")
        cl_confirmed = sum(1 for item in checklist if item.status == CheckStatus.CONFIRMED)
        cl_anomaly = sum(1 for item in checklist if item.status == CheckStatus.ANOMALY)
        cl_missing = sum(1 for item in checklist if item.status == CheckStatus.MISSING)
        cl_pending = sum(1 for item in checklist if item.status == CheckStatus.PENDING)
        lines.append(f"  總項目數:   {len(checklist)}")
        lines.append(f"  已確認:     {cl_confirmed}")
        lines.append(f"  異常:       {cl_anomaly}")
        lines.append(f"  缺漏:       {cl_missing}")
        lines.append(f"  待核:       {cl_pending}")
        lines.append("")

    lines.append(sep)
    lines.append("  本報告由 PDF 差異比對系統自動產生")
    lines.append(sep)
    lines.append("")

    output.write_text("\n".join(lines), encoding="utf-8")
    return str(output)


def export_review_log_csv(
    comparison_id: str,
    diff_report: DiffReport,
    checklist: list[ChecklistItem] | None,
    review_logs: list[dict[str, str | None]] | None,
    output_path: str,
) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    checklist = checklist or []
    review_logs = review_logs or []
    diff_by_id = {item.id: item for item in diff_report.items}
    checklist_by_diff_id: dict[str, list[str]] = {}
    fieldnames = [
        "比對ID",
        "舊版檔名",
        "新版檔名",
        "差異ID",
        "差異類型",
        "差異位置",
        "原始內容",
        "修訂內容",
        "對應檢核項目",
        "審核動作",
        "審核人員",
        "審核備註",
        "審核時間",
        "目前是否已審核",
        "目前審核人員",
        "目前審核時間",
    ]

    for item in checklist:
        if not item.matched_diff_id:
            continue
        checklist_by_diff_id.setdefault(item.matched_diff_id, []).append(item.item_id)

    rows: list[dict[str, str | None]] = []
    for log in review_logs:
        diff_id = log["diff_item_id"] or ""
        diff = diff_by_id.get(diff_id)
        rows.append(
            {
                "比對ID": comparison_id,
                "舊版檔名": diff_report.old_filename,
                "新版檔名": diff_report.new_filename,
                "差異ID": diff_id,
                "差異類型": diff.diff_type.value if diff else None,
                "差異位置": diff.context if diff else None,
                "原始內容": diff.old_value if diff else None,
                "修訂內容": diff.new_value if diff else None,
                "對應檢核項目": ",".join(checklist_by_diff_id.get(diff_id, [])) or None,
                "審核動作": log["action"],
                "審核人員": log["reviewer"],
                "審核備註": log["note"],
                "審核時間": log["created_at"],
                "目前是否已審核": str(diff.reviewed) if diff else None,
                "目前審核人員": diff.reviewed_by if diff else None,
                "目前審核時間": diff.reviewed_at if diff else None,
            }
        )

    if not rows:
        for diff in diff_report.items:
            rows.append(
                {
                    "比對ID": comparison_id,
                    "舊版檔名": diff_report.old_filename,
                    "新版檔名": diff_report.new_filename,
                    "差異ID": diff.id,
                    "差異類型": diff.diff_type.value,
                    "差異位置": diff.context,
                    "原始內容": diff.old_value,
                    "修訂內容": diff.new_value,
                    "對應檢核項目": ",".join(checklist_by_diff_id.get(diff.id, [])) or None,
                    "審核動作": None,
                    "審核人員": None,
                    "審核備註": None,
                    "審核時間": None,
                    "目前是否已審核": str(diff.reviewed),
                    "目前審核人員": diff.reviewed_by,
                    "目前審核時間": diff.reviewed_at,
                }
            )

    with output.open("w", encoding="utf-8-sig", newline="") as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)

    return str(output)
