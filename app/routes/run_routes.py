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
    Query,
    status,
)

from app.deps import get_executor, get_graph_store, get_run_store, get_tool_registry
from app.schemas import RunRequest, RunResponse, RunStateResponse, serialize_state_response
from engine.graph import Graph
from engine.state import WorkflowState

logger = logging.getLogger("workflow.routes.run")

router = APIRouter(prefix="/graph", tags=["run"])


def _execute_run(run_id: str, graph_id: str, graph_store, run_store, executor, registry) -> None:
    """Background execution helper."""

    try:
        graph_payload = graph_store.get(graph_id)
        graph = Graph.from_dict(graph_payload, registry=registry)
        record = run_store.get(run_id)
        result = executor.run(graph, record.state)
        run_store.update(run_id, status="completed", logs=result.logs, result=result)
        logger.info("Run %s completed", run_id)
    except Exception as exc:  # pragma: no cover - logging only
        logger.exception("Run %s failed: %s", run_id, exc)
        run_store.update(run_id, status="failed")


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
) -> RunResponse:
    """Launch a workflow run."""

    if not graph_store.exists(payload.graph_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph not found.")

    run_id = str(uuid4())
    initial_state = WorkflowState(context=payload.initial_state)
    from app.main import RunRecord  # circular avoidance kept local

    record = RunRecord(run_id=run_id, graph_id=payload.graph_id, state=initial_state)
    run_store.create(record)

    if payload.background:
        background_tasks.add_task(
            _execute_run,
            run_id,
            payload.graph_id,
            graph_store,
            run_store,
            executor,
            registry,
        )
    else:
        _execute_run(run_id, payload.graph_id, graph_store, run_store, executor, registry)

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
        record = run_store.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return serialize_state_response(record)

