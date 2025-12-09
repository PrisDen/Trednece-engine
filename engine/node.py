from __future__ import annotations

"""Node definitions for the workflow engine."""

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from engine.state import WorkflowState

NodeCallable = Callable[[WorkflowState], WorkflowState | Awaitable[WorkflowState]]


@dataclass(slots=True)
class Node:
    """Represents a workflow node wrapping an executable callable."""

    id: str
    name: str
    func: NodeCallable
    metadata: Dict[str, Any] = field(default_factory=dict)

    def execute(self, state: WorkflowState) -> WorkflowState | Awaitable[WorkflowState]:
        """Invoke the node callable with the provided state."""

        return self.func(state)


def build_node(
    node_id: str,
    *,
    name: Optional[str] = None,
    func: NodeCallable,
    metadata: Optional[Dict[str, Any]] = None,
) -> Node:
    """Factory helper to construct a Node."""

    return Node(
        id=node_id,
        name=name or node_id,
        func=func,
        metadata=metadata or {},
    )


__all__ = ["Node", "NodeCallable", "build_node"]

