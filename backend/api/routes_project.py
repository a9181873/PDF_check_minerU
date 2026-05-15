import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.routes_auth import get_current_user
from models.database import list_project_comparisons, list_projects, project_exists
from models.database import create_project as create_project_row
from models.schemas import ProjectCreateRequest, ProjectResponse

router = APIRouter(prefix="/api/projects", tags=["project"], dependencies=[Depends(get_current_user)])


@router.post("", response_model=ProjectResponse)
async def create_project_api(payload: ProjectCreateRequest):
    row = create_project_row(payload.name)
    return ProjectResponse(**row)


@router.get("", response_model=list[ProjectResponse])
async def list_projects_api():
    rows = list_projects()
    return [ProjectResponse(**row) for row in rows]


@router.get("/all/comparisons/export")
async def export_all_comparisons_csv():
    from models.database import list_all_comparisons_unlimited
    rows = list_all_comparisons_unlimited()

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["比對編號", "案號", "專案名稱", "舊版檔案", "新版檔案", "狀態", "審核人員", "建立時間", "完成時間", "錯誤訊息"])
    status_map = {"done": "已完成", "error": "錯誤", "pending": "待處理", "parsing": "處理中"}
    for row in rows:
        writer.writerow([
            row["id"],
            row["case_number"] or "",
            row["project_id"] or "",
            row["old_filename"] or "",
            row["new_filename"] or "",
            status_map.get(row["status"], row["status"]),
            row["latest_reviewer"] or "",
            row["created_at"] or "",
            row["completed_at"] or "",
            row["error_message"] or "",
        ])

    content = "﻿" + output.getvalue()
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=comparison_records.csv"},
    )


@router.get("/all/comparisons")
async def list_all_projects_comparisons_api(limit: int = 10):
    from models.database import list_all_comparisons
    return list_all_comparisons(limit)


@router.delete("/all/comparisons/{comparison_id}")
async def delete_comparison_api(comparison_id: str):
    from models.database import delete_comparison
    deleted = delete_comparison(comparison_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Comparison not found")
    return {"ok": True}


@router.get("/{project_id}/comparisons")
async def list_project_comparisons_api(project_id: str):
    if not project_exists(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return list_project_comparisons(project_id)
