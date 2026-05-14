from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from fastapi import Depends

from api.routes_archive import router as archive_router
from api.routes_auth import get_current_user, router as auth_router
from api.routes_compare import router as compare_router
from api.routes_checklist import router as checklist_router
from api.routes_export import router as export_router
from api.routes_project import router as project_router
from api.routes_review import router as review_router
from api.websocket import router as websocket_router
from config import settings
from models.database import ensure_default_admin, ensure_default_project, init_db

app = FastAPI(title=settings.app_name, debug=settings.debug)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router)
app.include_router(compare_router)
app.include_router(project_router)
app.include_router(review_router)
app.include_router(checklist_router)
app.include_router(export_router)
app.include_router(archive_router)
app.include_router(websocket_router)


@app.on_event("startup")
def on_startup() -> None:
    settings.old_upload_dir.mkdir(parents=True, exist_ok=True)
    settings.new_upload_dir.mkdir(parents=True, exist_ok=True)
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    settings.markdown_export_dir.mkdir(parents=True, exist_ok=True)
    settings.archive_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    ensure_default_project()
    ensure_default_admin()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system/resource-logs")
def get_resource_logs(limit: int = 50, _user: dict = Depends(get_current_user)):
    from services.resource_monitor import list_resource_logs
    return list_resource_logs(limit)


@app.get("/api/system/resource-logs/{task_id}")
def get_resource_log_detail_route(task_id: str, _user: dict = Depends(get_current_user)):
    from services.resource_monitor import get_resource_log_detail as _get_detail
    detail = _get_detail(task_id)
    if not detail:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Resource log not found")
    return detail


from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import FileResponse, JSONResponse

@app.exception_handler(StarletteHTTPException)
async def spa_exception_handler(request, exc):
    if exc.status_code == 404:
        # If request is not an API call and has no file extension, return index.html for React Router
        path = request.url.path
        if not path.startswith("/api/") and not path.startswith("/ws/") and "." not in path.split("/")[-1]:
            index_file = static_dir / "index.html"
            if index_file.exists():
                return FileResponse(index_file)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

static_dir = Path(__file__).resolve().parent / "static"

# Keep the SPA fallback mount last so API and health routes remain reachable.
app.mount("/uploads", StaticFiles(directory=settings.uploads_dir, check_dir=False), name="uploads")
app.mount("/", StaticFiles(directory=static_dir, html=True, check_dir=False), name="static")
