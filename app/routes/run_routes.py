from __future__ import annotations

"""Run execution routes."""

import logging
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Path,
    status,
)

from app.deps import (
    get_executor,
    get_graph_store,
    get_log_stream_manager,
    get_run_store,
    get_tool_registry,
)
from app.schemas import RunRequest, RunResponse, RunStateResponse, serialize_state_response
from engine.graph import Graph
from engine.state import WorkflowState

logger = logging.getLogger("workflow.routes.run")

router = APIRouter(prefix="/graph", tags=["run"])


async def _execute_run(
    run_id: str,
    graph_id: str,
    graph_store,
    run_store,
    executor,
    registry,
    manager,
) -> None:
    """Background execution helper."""

    try:
        graph_payload = graph_store.get(graph_id)
        graph = Graph.from_dict(graph_payload, registry=registry)
        record = await run_store.get(run_id)

        def emit(log):
            record.logs.append(log)
            manager.publish(run_id, {"type": "log", "log": log.model_dump()})

        def is_cancelled() -> bool:
            return record.cancelled

        manager.publish(run_id, {"type": "status", "status": "running"})
        result = await executor.run_background(
            graph,
            record.state,
            log_hook=emit,
            cancel_checker=is_cancelled,
        )
        final_status = result.final_state.status
        await run_store.update(run_id, status=final_status, logs=result.logs, result=result)
        manager.publish(run_id, {"type": "status", "status": final_status})
        logger.info("Run %s %s", run_id, final_status)
    except Exception as exc:  # pragma: no cover - logging only
        logger.exception("Run %s failed: %s", run_id, exc)
        await run_store.update(run_id, status="failed")
        manager.publish(run_id, {"type": "status", "status": "failed", "error": str(exc)})


@router.post(
    "/run",
    response_model=RunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def launch_run(
    payload: RunRequest,
    background_tasks: BackgroundTasks,
    graph_store=Depends(get_graph_store),
    run_store=Depends(get_run_store),
    executor=Depends(get_executor),
    registry=Depends(get_tool_registry),
    manager=Depends(get_log_stream_manager),
) -> RunResponse:
    """Launch a workflow run."""

    if not graph_store.exists(payload.graph_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph not found.")

    run_id = str(uuid4())
    initial_state = WorkflowState(context=payload.initial_state)
    from app.main import RunRecord  # circular avoidance kept local

    record = RunRecord(run_id=run_id, graph_id=payload.graph_id, state=initial_state)
    await run_store.create(record)

    task_args = (
        run_id,
        payload.graph_id,
        graph_store,
        run_store,
        executor,
        registry,
        manager,
    )

    if payload.background:
        background_tasks.add_task(_execute_run, *task_args)
    else:
        await _execute_run(*task_args)

    return RunResponse(run_id=run_id, graph_id=payload.graph_id, status=record.status)


@router.get(
    "/state/{run_id}",
    response_model=RunStateResponse,
    status_code=status.HTTP_200_OK,
)
async def get_run_state(
    run_id: str = Path(..., description="Run identifier"),
    run_store=Depends(get_run_store),
) -> RunStateResponse:
    """Return run state and logs."""

    try:
        record = await run_store.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return serialize_state_response(record)


@router.post(
    "/cancel/{run_id}",
    response_model=RunResponse,
    status_code=status.HTTP_200_OK,
)
async def cancel_run(
    run_id: str,
    run_store=Depends(get_run_store),
    manager=Depends(get_log_stream_manager),
) -> RunResponse:
    """Request cancellation of an active run."""

    try:
        record = await run_store.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if record.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run '{run_id}' is already finished.",
        )

    await run_store.request_cancel(run_id)
    manager.publish(run_id, {"type": "status", "status": "cancelled", "message": "Cancellation requested"})
    logger.info("Cancellation requested for run %s", run_id)
    return RunResponse(run_id=run_id, graph_id=record.graph_id, status="cancelled")

