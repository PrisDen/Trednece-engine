from __future__ import annotations

"""Workflow execution engine with branching, looping, and logging."""

import asyncio
from collections import defaultdict
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Iterable, Literal, Optional
import ast
import operator

from pydantic import BaseModel, Field

from engine.graph import Edge, Graph, LoopConfig
from engine.node import Node
from engine.state import WorkflowState

ExecutionLogStatus = Literal["success", "failed", "cancelled"]


class ExecutionError(Exception):
    """Base class for execution-related failures."""


class LoopLimitExceeded(ExecutionError):
    """Raised when a loop exceeds the configured iteration limit."""


class NodeTimeoutError(ExecutionError):
    """Raised when a node exceeds its execution timeout."""


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
    """Workflow executor with async-aware node execution."""

    def __init__(
        self,
        *,
        sandbox_globals: Dict[str, Any] | None = None,
        node_timeout: float | None = 30.0,
        cancel_poll_interval: float = 0.1,
    ) -> None:
        self._sandbox_globals = sandbox_globals or {}
        self._node_timeout = node_timeout
        self._cancel_poll_interval = cancel_poll_interval

    async def run_async(
        self,
        graph: Graph,
        state: WorkflowState,
        *,
        log_hook: Optional[Callable[[ExecutionLog], None]] = None,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> ExecutionResult:
        """Execute the graph asynchronously and return the final state."""

        return await self._run_async(
            graph,
            state,
            log_hook=log_hook,
            cancel_checker=cancel_checker,
        )

    def run(
        self,
        graph: Graph,
        state: WorkflowState,
        *,
        log_hook: Optional[Callable[[ExecutionLog], None]] = None,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> ExecutionResult:
        """Synchronous wrapper for non-event-loop callers."""

        try:
            asyncio.get_running_loop()
            raise RuntimeError("Executor.run cannot be called from an active event loop; use run_async")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(
                    self._run_async(
                        graph,
                        state,
                        log_hook=log_hook,
                        cancel_checker=cancel_checker,
                    )
                )
            finally:
                loop.close()

    async def run_background(
        self,
        graph: Graph,
        state: WorkflowState,
        *,
        log_hook: Optional[Callable[[ExecutionLog], None]] = None,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> ExecutionResult:
        """Execute the graph without blocking the event loop."""

        return await self._run_async(
            graph,
            state,
            log_hook=log_hook,
            cancel_checker=cancel_checker,
        )

    def run_once(self, node: Node, state: WorkflowState) -> tuple[WorkflowState, ExecutionLog]:
        """Execute a single node and return updated state and log (sync wrapper)."""

        try:
            asyncio.get_running_loop()
            raise RuntimeError("Executor.run_once cannot be called from an active event loop; use run_once_async")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self.run_once_async(node, state))
            finally:
                loop.close()

    async def run_once_async(
        self,
        node: Node,
        state: WorkflowState,
        *,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> tuple[WorkflowState, ExecutionLog]:
        """Execute a single node asynchronously and return updated state and log."""

        try:
            new_state = await self._invoke_node(node, state, cancel_checker=cancel_checker)
        except asyncio.TimeoutError as exc:
            state.record(
                node_id=node.id,
                message="Node execution timed out",
                data={"error": str(exc)},
            )
            log_entry = ExecutionLog(
                node_id=node.id,
                status="failed",
                message="Node execution timed out",
                error="timeout",
            )
            raise NodeTimeoutError(log_entry.message or "timeout") from exc
        except asyncio.CancelledError as exc:
            state.record(
                node_id=node.id,
                message="Node execution cancelled",
            )
            log_entry = ExecutionLog(
                node_id=node.id,
                status="cancelled",
                message="Node execution cancelled",
            )
            raise NodeExecutionError(log_entry, exc) from exc
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
        """Evaluate expressions with an AST-based safe evaluator."""

        allowed_ops = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
            ast.Eq: operator.eq,
            ast.NotEq: operator.ne,
            ast.Lt: operator.lt,
            ast.LtE: operator.le,
            ast.Gt: operator.gt,
            ast.GtE: operator.ge,
            ast.And: operator.and_,
            ast.Or: operator.or_,
            ast.Not: operator.not_,
        }

        def eval_node(node):
            if isinstance(node, ast.Expression):
                return eval_node(node.body)
            if isinstance(node, ast.Constant):
                return node.value
            if isinstance(node, ast.Name):
                if node.id == "state":
                    return state
                if node.id == "context":
                    return state.context
                raise ValueError(f"Name '{node.id}' is not allowed")
            if isinstance(node, ast.Subscript):
                container = eval_node(node.value)
                key = eval_node(node.slice)
                return container[key]
            if isinstance(node, ast.Call):
                # allow context.get(key, default) only
                if isinstance(node.func, ast.Attribute):
                    if isinstance(node.func.value, ast.Name) and node.func.value.id == "context" and node.func.attr == "get":
                        args = [eval_node(arg) for arg in node.args]
                        kwargs = {kw.arg: eval_node(kw.value) for kw in node.keywords}
                        return state.context.get(*args, **kwargs)
                raise ValueError("Function calls are not allowed")
            if isinstance(node, ast.Attribute):
                raise ValueError("Attribute access not allowed")
            if isinstance(node, ast.BinOp):
                left = eval_node(node.left)
                right = eval_node(node.right)
                op = allowed_ops.get(type(node.op))
                if not op:
                    raise ValueError("Operator not allowed")
                return op(left, right)
            if isinstance(node, ast.BoolOp):
                vals = [eval_node(v) for v in node.values]
                op = allowed_ops.get(type(node.op))
                if not op:
                    raise ValueError("Bool operator not allowed")
                result = vals[0]
                for v in vals[1:]:
                    result = op(result, v)
                return result
            if isinstance(node, ast.UnaryOp):
                operand = eval_node(node.operand)
                op = allowed_ops.get(type(node.op))
                if not op:
                    raise ValueError("Unary operator not allowed")
                return op(operand)
            if isinstance(node, ast.Compare):
                left = eval_node(node.left)
                result = True
                for op_node, comparator in zip(node.ops, node.comparators):
                    op = allowed_ops.get(type(op_node))
                    if not op:
                        raise ValueError("Comparison operator not allowed")
                    right = eval_node(comparator)
                    if not op(left, right):
                        result = False
                        break
                    left = right
                return result
            raise ValueError("Expression not allowed")

        tree = ast.parse(expression, mode="eval")
        return eval_node(tree)

    async def _run_async(
        self,
        graph: Graph,
        state: WorkflowState,
        *,
        log_hook: Optional[Callable[[ExecutionLog], None]] = None,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> ExecutionResult:
        """Async implementation backing run/run_background."""

        logs: list[ExecutionLog] = []
        loop_counters: Dict[tuple[str, str], int] = defaultdict(int)
        current_node_id = graph.start_node
        state.status = "running"

        while current_node_id:
            if cancel_checker and cancel_checker():
                cancel_log = ExecutionLog(
                    node_id=current_node_id or "executor",
                    status="cancelled",
                    message="Run cancelled by user",
                )
                logs.append(cancel_log)
                if log_hook:
                    log_hook(cancel_log)
                state.status = "cancelled"
                break

            node = graph.get_node(current_node_id)
            try:
                state, log_entry = await self.run_once_async(
                    node,
                    state,
                    cancel_checker=cancel_checker,
                )
                logs.append(log_entry)
                if log_hook:
                    log_hook(log_entry)
            except NodeExecutionError as exc:
                logs.append(exc.log)
                if log_hook:
                    log_hook(exc.log)
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
                if log_hook:
                    log_hook(failure_log)
                state.status = "failed"
                raise

            current_node_id = next_node

        if state.status != "cancelled":
            state.status = "completed"
        return ExecutionResult(run_id=str(state.run_id), final_state=state, logs=logs)

    async def _invoke_node(
        self,
        node: Node,
        state: WorkflowState,
        *,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> WorkflowState:
        """Invoke a node function with timeout and cooperative cancellation."""

        func = node.func

        async def run_func() -> WorkflowState:
            if cancel_checker and cancel_checker():
                raise asyncio.CancelledError()
            if asyncio.iscoroutinefunction(func):
                return await func(state)
            return await asyncio.to_thread(func, state)

        task = asyncio.create_task(run_func())

        async def cancel_watcher() -> None:
            if not cancel_checker:
                return
            while not task.done():
                if cancel_checker():
                    task.cancel()
                    break
                await asyncio.sleep(self._cancel_poll_interval)

        watcher = asyncio.create_task(cancel_watcher())

        try:
            result = await asyncio.wait_for(task, timeout=self._node_timeout)
        finally:
            watcher.cancel()
        return result


__all__ = [
    "ExecutionError",
    "ExecutionLog",
    "ExecutionResult",
    "Executor",
    "LoopLimitExceeded",
    "NodeExecutionError",
]

