from __future__ import annotations

"""Workflow execution engine with branching, looping, and logging."""

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, Literal

from pydantic import BaseModel, Field

from engine.graph import Edge, Graph, LoopConfig
from engine.node import Node
from engine.state import WorkflowState

ExecutionLogStatus = Literal["success", "failed"]


class ExecutionError(Exception):
    """Base class for execution-related failures."""


class LoopLimitExceeded(ExecutionError):
    """Raised when a loop exceeds the configured iteration limit."""


class NodeExecutionError(ExecutionError):
    """Wraps node failures with structured logging."""

    def __init__(self, log: ExecutionLog, original: Exception) -> None:
        super().__init__(log.error or log.message or "Node execution failed")
        self.log = log
        self.original = original


class ExecutionLog(BaseModel):
    """Structured log entry for a node execution."""

    node_id: str
    status: ExecutionLogStatus
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    message: str | None = None
    error: str | None = None


class ExecutionResult(BaseModel):
    """Aggregate result for an entire workflow run."""

    run_id: str
    final_state: WorkflowState
    logs: list[ExecutionLog]


class Executor:
    """Synchronous workflow executor."""

    def __init__(self, *, sandbox_globals: Dict[str, Any] | None = None) -> None:
        self._sandbox_globals = sandbox_globals or {}

    def run(self, graph: Graph, state: WorkflowState) -> ExecutionResult:
        """Execute the graph sequentially and return the final state."""

        logs: list[ExecutionLog] = []
        loop_counters: Dict[tuple[str, str], int] = defaultdict(int)
        current_node_id = graph.start_node
        state.status = "running"

        while current_node_id:
            node = graph.get_node(current_node_id)
            try:
                state, log_entry = self.run_once(node, state)
                logs.append(log_entry)
            except NodeExecutionError as exc:
                logs.append(exc.log)
                state.status = "failed"
                raise exc

            try:
                next_node = self._select_next_node(
                    graph.get_edges(current_node_id),
                    state,
                    loop_counters,
                )
            except ExecutionError as exc:
                failure_log = ExecutionLog(
                    node_id=current_node_id,
                    status="failed",
                    message="Loop evaluation failed",
                    error=str(exc),
                )
                logs.append(failure_log)
                state.status = "failed"
                raise

            current_node_id = next_node

        state.status = "completed"
        return ExecutionResult(run_id=str(state.run_id), final_state=state, logs=logs)

    async def run_background(self, graph: Graph, state: WorkflowState) -> ExecutionResult:
        """Execute the graph in a background thread for async contexts."""

        return await asyncio.to_thread(self.run, graph, state)

    def run_once(self, node: Node, state: WorkflowState) -> tuple[WorkflowState, ExecutionLog]:
        """Execute a single node and return updated state and log."""

        try:
            new_state = node.execute(state)
        except Exception as exc:  # pragma: no cover - defensive guard
            state.record(
                node_id=node.id,
                message="Node execution failed",
                data={"error": str(exc)},
            )
            log_entry = ExecutionLog(
                node_id=node.id,
                status="failed",
                message="Node execution failed",
                error=str(exc),
            )
            raise NodeExecutionError(log_entry, exc) from exc

        if not isinstance(new_state, WorkflowState):
            log_entry = ExecutionLog(
                node_id=node.id,
                status="failed",
                message="Node returned invalid state",
                error=f"Expected WorkflowState, got {type(new_state)!r}",
            )
            raise NodeExecutionError(log_entry, TypeError(log_entry.error))

        new_state.record(node_id=node.id, message="Node executed successfully")
        log_entry = ExecutionLog(node_id=node.id, status="success")
        return new_state, log_entry

    def _select_next_node(
        self,
        edges: Iterable[Edge],
        state: WorkflowState,
        loop_counters: Dict[tuple[str, str], int],
    ) -> str | None:
        """Determine the next node based on edge types, conditions, and loops."""

        for edge in edges:
            if edge.type == "sequential":
                return edge.target
            if edge.type == "branch" and self._evaluate_branch(edge, state):
                return edge.target
            if edge.type == "loop" and self._should_continue_loop(edge, state, loop_counters):
                return edge.target
        return None

    def _evaluate_branch(self, edge: Edge, state: WorkflowState) -> bool:
        """Evaluate a branch edge condition."""

        condition = edge.condition or {}
        callable_candidate = condition.get("callable")
        if callable(callable_candidate):
            return bool(callable_candidate(state))

        expression = condition.get("expression")
        language = condition.get("language", "python")
        if expression and language == "python":
            return bool(self._safe_eval(expression, state))

        return False

    def _should_continue_loop(
        self,
        edge: Edge,
        state: WorkflowState,
        loop_counters: Dict[tuple[str, str], int],
    ) -> bool:
        """Determine whether a loop edge should be traversed."""

        config = edge.loop or LoopConfig()
        if config.until_expression and self._safe_eval(config.until_expression, state):
            return False

        key = (edge.source, edge.target)
        loop_counters[key] += 1
        if loop_counters[key] > config.max_iterations:
            raise LoopLimitExceeded(
                f"Loop {edge.source}->{edge.target} exceeded {config.max_iterations} iterations."
            )
        return True

    def _safe_eval(self, expression: str, state: WorkflowState) -> Any:
        """Evaluate limited expressions against the workflow state."""

        allowed_globals = {"__builtins__": {}}
        allowed_locals = {
            "state": state,
            "context": state.context,
            **self._sandbox_globals,
        }
        return eval(expression, allowed_globals, allowed_locals)


__all__ = [
    "ExecutionError",
    "ExecutionLog",
    "ExecutionResult",
    "Executor",
    "LoopLimitExceeded",
    "NodeExecutionError",
]

