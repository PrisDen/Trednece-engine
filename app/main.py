from __future__ import annotations

"""FastAPI application factory and runtime stores."""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict

from fastapi import FastAPI

from engine.executor import ExecutionLog, ExecutionResult, Executor
from engine.registry import ToolRegistry
from engine.state import ExecutionStatus, WorkflowState
from app.routes import graph_routes, run_routes, ws_routes
from app.ws import LogStreamManager

logger = logging.getLogger("workflow.app")


def configure_logging() -> None:
    """Configure basic logging for the service."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class GraphStore:
    """In-memory store for persisted graph definitions."""

    def __init__(self) -> None:
        self._graphs: Dict[str, Dict[str, Any]] = {}

    def save(self, graph_id: str, payload: Dict[str, Any]) -> None:
        """Persist a graph definition."""

        self._graphs[graph_id] = payload

    def get(self, graph_id: str) -> Dict[str, Any]:
        """Retrieve a graph definition."""

        try:
            return self._graphs[graph_id]
        except KeyError as exc:
            raise KeyError(f"Graph '{graph_id}' not found.") from exc

    def exists(self, graph_id: str) -> bool:
        """Check whether a graph is stored."""

        return graph_id in self._graphs


@dataclass
class RunRecord:
    """Tracks execution metadata and resulting state."""

    run_id: str
    graph_id: str
    state: WorkflowState
    status: ExecutionStatus = "pending"
    logs: list[ExecutionLog] = field(default_factory=list)
    result: ExecutionResult | None = None
    cancelled: bool = False


class RunStore:
    """In-memory store for workflow run records."""

    def __init__(self) -> None:
        self._runs: Dict[str, RunRecord] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _lock_for(self, run_id: str) -> asyncio.Lock:
        lock = self._locks.get(run_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[run_id] = lock
        return lock

    async def create(self, record: RunRecord) -> None:
        """Persist a new run record."""

        async with self._lock_for(record.run_id):
            self._runs[record.run_id] = record

    async def update(
        self,
        run_id: str,
        *,
        status: ExecutionStatus | None = None,
        logs: list[ExecutionLog] | None = None,
        result: ExecutionResult | None = None,
    ) -> None:
        """Update existing run metadata."""

        async with self._lock_for(run_id):
            record = self._runs.get(run_id)
            if not record:
                raise KeyError(f"Run '{run_id}' not found.")
            if status:
                record.status = status
            if logs:
                record.logs = logs
            if result:
                record.result = result

    async def get(self, run_id: str) -> RunRecord:
        """Fetch a run by identifier."""

        async with self._lock_for(run_id):
            try:
                return self._runs[run_id]
            except KeyError as exc:
                raise KeyError(f"Run '{run_id}' not found.") from exc

    async def request_cancel(self, run_id: str) -> RunRecord:
        """Mark a run for cancellation."""

        async with self._lock_for(run_id):
            record = self._runs.get(run_id)
            if not record:
                raise KeyError(f"Run '{run_id}' not found.")
            record.cancelled = True
            record.status = "cancelled"
            return record


def _register_builtin_tools(registry: ToolRegistry) -> None:
    """Register a minimal set of default tools."""

    def noop(state: WorkflowState) -> WorkflowState:
        state.record("noop", "No-op tool executed")
        return state

    def approve(state: WorkflowState) -> WorkflowState:
        state.update_context(approved=True)
        return state

    for name, func in {
        "tools.noop": noop,
        "tools.approve": approve,
    }.items():
        if not registry.has(name):
            registry.register(name, func)


def create_app() -> FastAPI:
    """Construct the FastAPI application."""

    configure_logging()
    registry = ToolRegistry()
    _register_builtin_tools(registry)

    graph_store = GraphStore()
    run_store = RunStore()
    executor = Executor()
    log_stream_manager = LogStreamManager()

    app = FastAPI(title="Workflow Engine", version="0.1.0")

    app.state.graph_store = graph_store
    app.state.run_store = run_store
    app.state.tool_registry = registry
    app.state.executor = executor
    app.state.log_stream_manager = log_stream_manager

    @app.on_event("startup")
    async def _startup() -> None:
        log_stream_manager.bind_loop(asyncio.get_running_loop())
        logger.info("Workflow service starting up.")

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        logger.info("Workflow service shutting down.")

    @app.get("/health", tags=["system"])
    async def health() -> Dict[str, str]:
        """Simple health probe."""

        return {"status": "ok"}

    app.include_router(graph_routes.router)
    app.include_router(run_routes.router)
    app.include_router(ws_routes.router)

    return app


app = create_app()


__all__ = [
    "GraphStore",
    "RunRecord",
    "RunStore",
    "app",
    "create_app",
]

