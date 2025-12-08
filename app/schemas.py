from __future__ import annotations

"""Request and response schemas for the workflow API."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, RootModel

from engine.state import ExecutionStatus, WorkflowState


# Graph Schemas ----------------------------------------------------------------


class NodeInput(BaseModel):
    """Incoming node definition as provided by clients."""

    id: str
    callable: str
    name: str | None = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EdgeInput(BaseModel):
    """Incoming edge definition supporting branch/loop metadata."""

    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    type: str = "sequential"
    condition: Dict[str, Any] | None = None
    loop: Dict[str, Any] | None = None

    class Config:
        allow_population_by_field_name = True


class GraphCreateRequest(BaseModel):
    """Payload for POST /graph/create."""

    id: str
    name: str
    start_node: str
    nodes: List[NodeInput]
    edges: List[EdgeInput]


class GraphCreateResponse(BaseModel):
    """Response for graph creation."""

    graph_id: str
    message: str = "Graph registered"


# Run Schemas ------------------------------------------------------------------


class RunRequest(BaseModel):
    """Payload for POST /graph/run."""

    graph_id: str
    initial_state: Dict[str, Any] = Field(default_factory=dict)
    background: bool = False


class ExecutionLogSchema(BaseModel):
    """Serializable execution log entry."""

    node_id: str
    status: str
    timestamp: datetime
    message: str | None = None
    error: str | None = None


class RunResponse(BaseModel):
    """Response returned when a run is scheduled or completed."""

    run_id: str
    graph_id: str
    status: ExecutionStatus


class RunStateResponse(BaseModel):
    """Response for GET /graph/state/{run_id}."""

    run_id: str
    graph_id: str
    status: ExecutionStatus
    context: Dict[str, Any]
    logs: List[ExecutionLogSchema]


class ExecutionResultSchema(BaseModel):
    """Full execution result returned to clients."""

    run_id: str
    status: ExecutionStatus
    context: Dict[str, Any]
    logs: List[ExecutionLogSchema]


def serialize_state_response(run_record) -> RunStateResponse:
    """Convert an internal RunRecord to API schema."""

    logs = [
        ExecutionLogSchema(
            node_id=log.node_id,
            status=log.status,
            timestamp=log.timestamp,
            message=log.message,
            error=log.error,
        )
        for log in run_record.logs
    ]

    return RunStateResponse(
        run_id=run_record.run_id,
        graph_id=run_record.graph_id,
        status=run_record.status,
        context=run_record.state.context,
        logs=logs,
    )


__all__ = [
    "EdgeInput",
    "ExecutionLogSchema",
    "ExecutionResultSchema",
    "GraphCreateRequest",
    "GraphCreateResponse",
    "NodeInput",
    "RunRequest",
    "RunResponse",
    "RunStateResponse",
    "serialize_state_response",
]

