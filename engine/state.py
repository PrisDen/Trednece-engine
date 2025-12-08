from __future__ import annotations

"""Shared state models and typing helpers for the workflow engine."""

from datetime import datetime
from typing import Any, Callable, Dict, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

ExecutionStatus = Literal["pending", "running", "completed", "failed"]
"""Valid lifecycle states for a workflow run."""

BranchCondition = Callable[["WorkflowState"], bool]
"""Callable signature for evaluating branch conditions."""


class StateSnapshot(BaseModel):
    """Immutable record of state at a point in the workflow."""

    node_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    message: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


class WorkflowState(BaseModel):
    """Shared mutable workflow state passed between nodes."""

    run_id: UUID = Field(default_factory=uuid4)
    status: ExecutionStatus = "pending"
    context: Dict[str, Any] = Field(default_factory=dict)
    history: list[StateSnapshot] = Field(default_factory=list)

    class Config:
        frozen = False

    def record(
        self,
        node_id: str,
        message: str | None = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append a snapshot to the execution history."""

        snapshot = StateSnapshot(
            node_id=node_id,
            message=message,
            data=data or {},
        )
        self.history.append(snapshot)

    def update_context(self, **kwargs: Any) -> None:
        """Convenience helper to mutate the context in-place."""

        self.context.update(kwargs)


__all__ = [
    "BranchCondition",
    "ExecutionStatus",
    "StateSnapshot",
    "WorkflowState",
]

