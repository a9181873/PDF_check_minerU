import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from api.routes_auth import decode_token
from api.task_store import TASK_STORE
from models.database import get_user_by_id

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/compare/{task_id}")
async def compare_progress_socket(websocket: WebSocket, task_id: str):
    # Auth via ?token= query string (browser WebSocket can't set Authorization header)
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user = get_user_by_id(payload["sub"])
    if not user or not user.get("is_active"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    last_signature: tuple[str, int, str, str | None] | None = None
    try:
        while True:
            state = TASK_STORE.get(task_id)
            if not state:
                # Task not in memory (e.g., after server restart) — fall back to DB.
                from models.database import get_comparison, get_comparison_report
                row = get_comparison(task_id)
                if not row:
                    await websocket.send_json({"event": "error", "data": {"message": "Task not found"}})
                    break
                db_status = row.get("status", "pending")
                if db_status == "done":
                    report = get_comparison_report(task_id)
                    if report:
                        await websocket.send_json({
                            "event": "complete",
                            "data": report.model_dump(mode="json"),
                        })
                    else:
                        await websocket.send_json({"event": "error", "data": {"message": "Result data not found"}})
                elif db_status == "error":
                    await websocket.send_json({
                        "event": "error",
                        "data": {"message": row.get("error_message") or "Processing error"},
                    })
                else:
                    # Task was mid-processing when server restarted — unrecoverable
                    await websocket.send_json({
                        "event": "error",
                        "data": {"message": "任務因伺服器重啟中斷，請重新上傳比較"},
                    })
                break

            signature = (
                state.status,
                state.progress_percent,
                state.current_step,
                state.error_message,
            )
            if signature != last_signature:
                await websocket.send_json(
                    {
                        "event": "progress",
                        "data": {
                            "status": state.status,
                            "step": state.current_step,
                            "percent": state.progress_percent,
                        },
                    }
                )
                last_signature = signature

            if state.status == "done":
                report = state.result
                if report is None:
                    from models.database import get_comparison_report
                    report = get_comparison_report(task_id)

                if report:
                    await websocket.send_json(
                        {
                            "event": "complete",
                            "data": report.model_dump(mode="json"),
                        }
                    )
                else:
                    await websocket.send_json({"event": "error", "data": {"message": "Result data not found"}})
                break

            if state.status == "error":
                await websocket.send_json(
                    {
                        "event": "error",
                        "data": {
                            "message": state.error_message or "Unknown processing error",
                        },
                    }
                )
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return
