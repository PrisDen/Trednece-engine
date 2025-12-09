from __future__ import annotations

"""Graph-related API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_graph_store, get_tool_registry
from app.schemas import GraphCreateRequest, GraphCreateResponse
from engine.graph import Graph

logger = logging.getLogger("workflow.routes.graph")

router = APIRouter(prefix="/graph", tags=["graph"])


@router.post(
    "/create",
    response_model=GraphCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_graph(
    payload: GraphCreateRequest,
    graph_store=Depends(get_graph_store),
    registry=Depends(get_tool_registry),
) -> GraphCreateResponse:
    """Register a new workflow graph."""

    if graph_store.exists(payload.id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Graph '{payload.id}' already exists.",
        )

    try:
        graph = Graph.from_dict(payload.model_dump(by_alias=True), registry=registry)
    except ValueError as exc:
        logger.exception("Graph validation failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    graph_store.save(graph.id, payload.model_dump(by_alias=True))
    logger.info("Registered graph %s", graph.id)
    return GraphCreateResponse(graph_id=graph.id)

