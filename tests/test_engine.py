from __future__ import annotations

"""Unit tests for core engine components."""

import asyncio
import pytest

from engine.executor import Executor, LoopLimitExceeded, NodeTimeoutError
from engine.graph import Graph
from engine.registry import ToolRegistry
from engine.state import WorkflowState


@pytest.fixture
def registry() -> ToolRegistry:
    registry = ToolRegistry()

    def noop(state: WorkflowState) -> WorkflowState:
        state.record("noop", "noop executed")
        return state

    def flag(state: WorkflowState) -> WorkflowState:
        state.update_context(flag=True)
        state.record("flag", "flag set")
        return state

    registry.register("tools.noop", noop)
    registry.register("tools.flag", flag)
    return registry


def build_graph_payload() -> dict:
    return {
        "id": "basic",
        "name": "Basic Graph",
        "start_node": "start",
        "nodes": [
            {"id": "start", "callable": "tools.noop"},
            {"id": "finish", "callable": "tools.flag"},
        ],
        "edges": [
            {"from": "start", "to": "finish", "type": "sequential"},
        ],
    }


def test_graph_loading(registry: ToolRegistry) -> None:
    graph = Graph.from_dict(build_graph_payload(), registry=registry)
    assert graph.start_node == "start"
    assert set(graph.nodes.keys()) == {"start", "finish"}


def test_executor_runs_sequential_graph(registry: ToolRegistry) -> None:
    graph = Graph.from_dict(build_graph_payload(), registry=registry)
    executor = Executor()
    result = executor.run(graph, WorkflowState())
    assert result.final_state.status == "completed"
    assert result.final_state.context["flag"] is True


def test_branching_routes_based_on_context(registry: ToolRegistry) -> None:
    payload = {
        "id": "branching",
        "name": "Branching Graph",
        "start_node": "review",
        "nodes": [
            {"id": "review", "callable": "tools.noop"},
            {"id": "approve", "callable": "tools.flag"},
            {"id": "fix", "callable": "tools.noop"},
        ],
        "edges": [
            {
                "from": "review",
                "to": "approve",
                "type": "branch",
                "condition": {"expression": "context.get('issues', 0) == 0"},
            },
            {
                "from": "review",
                "to": "fix",
                "type": "branch",
                "condition": {"expression": "context.get('issues', 0) > 0"},
            },
        ],
    }
    graph = Graph.from_dict(payload, registry=registry)
    executor = Executor()

    state = WorkflowState(context={"issues": 0})
    result = executor.run(graph, state)
    assert result.final_state.context["flag"] is True

    state_two = WorkflowState(context={"issues": 2})
    result_two = executor.run(graph, state_two)
    assert "flag" not in result_two.final_state.context


def test_loop_guard_prevents_infinite_cycles(registry: ToolRegistry) -> None:
    payload = {
        "id": "loop",
        "name": "Loop Graph",
        "start_node": "review",
        "nodes": [
            {"id": "review", "callable": "tools.noop"},
            {"id": "fix", "callable": "tools.noop"},
        ],
        "edges": [
            {
                "from": "review",
                "to": "fix",
                "type": "sequential",
            },
            {
                "from": "fix",
                "to": "review",
                "type": "loop",
                "loop": {"max_iterations": 1},
            },
        ],
    }
    graph = Graph.from_dict(payload, registry=registry)
    executor = Executor()

    with pytest.raises(LoopLimitExceeded):
        executor.run(graph, WorkflowState())


def test_safe_eval_blocks_attributes(registry: ToolRegistry) -> None:
    graph = Graph.from_dict(build_graph_payload(), registry=registry)
    executor = Executor()
    with pytest.raises(ValueError):
        executor._safe_eval("__import__('os').system('echo dangerous')", WorkflowState())


def test_node_timeout_triggers_failure(registry: ToolRegistry) -> None:
    async def slow(state: WorkflowState) -> WorkflowState:
        await asyncio.sleep(0.05)
        return state

    registry.register("tools.slow", slow)
    payload = {
        "id": "timeout",
        "name": "Timeout Graph",
        "start_node": "slow",
        "nodes": [{"id": "slow", "callable": "tools.slow"}],
        "edges": [],
    }
    graph = Graph.from_dict(payload, registry=registry)
    executor = Executor(node_timeout=0.01)
    with pytest.raises(NodeTimeoutError):
        asyncio.run(executor.run_async(graph, WorkflowState()))

