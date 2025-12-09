from __future__ import annotations

"""WebSocket routes for streaming execution logs."""

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status

from app.deps import get_log_stream_manager, get_run_store

logger = logging.getLogger("workflow.routes.ws")

router = APIRouter()


@router.websocket("/ws/logs/{run_id}")
async def stream_logs(
    websocket: WebSocket,
    run_id: str,
    run_store=Depends(get_run_store),
    manager=Depends(get_log_stream_manager),
) -> None:
    """Stream run logs to the connected client."""

    await websocket.accept()
    try:
        record = run_store.get(run_id)
    except KeyError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Unknown run_id")
        return

    queue = manager.register(run_id)

    try:
        for log in record.logs:
            await websocket.send_json({"type": "log", "log": log.model_dump()})
        if record.status in {"completed", "failed", "cancelled"}:
            await websocket.send_json({"type": "status", "status": record.status})

        while True:
            message = await queue.get()
            await websocket.send_json(message)
            if message.get("type") == "status":
                break
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for run %s", run_id)
    finally:
        manager.unregister(run_id, queue)
        try:
            await websocket.close()
        except RuntimeError:
            pass

