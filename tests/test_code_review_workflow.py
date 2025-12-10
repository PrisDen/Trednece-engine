"""Integration tests for the Code Review Mini-Agent workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.executor import Executor
from engine.graph import Graph
from engine.registry import ToolRegistry
from engine.state import WorkflowState
from tools.code_review_mini import (
    check_complexity,
    detect_basic_issues,
    evaluate_quality,
    extract_functions,
    suggest_improvements,
)


# Sample code snippets for testing
SAMPLE_CODE_SIMPLE = '''
def greet(name: str) -> str:
    """Return a greeting message."""
    return f"Hello, {name}!"


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''

SAMPLE_CODE_WITH_ISSUES = '''
def calculate_something(a, b, c, d, e, f, g):
    # TODO: add proper documentation
    result = 0
    if a > 0:
        if b > 0:
            if c > 0:
                result = a + b + c
            else:
                result = a + b
        else:
            if d > 0:
                result = a + d
            else:
                result = a
    else:
        if e > 0:
            result = e
        elif f > 0:
            result = f
        else:
            result = g
    return result


def another_function_without_docstring(x):
    very_long_variable_name_that_makes_this_line_exceed_the_maximum_allowed_character_limit = x * 2
    return very_long_variable_name_that_makes_this_line_exceed_the_maximum_allowed_character_limit
'''


@pytest.fixture
def registry() -> ToolRegistry:
    """Create a registry with code review tools registered."""
    reg = ToolRegistry()
    reg.register("extract_functions", extract_functions)
    reg.register("check_complexity", check_complexity)
    reg.register("detect_basic_issues", detect_basic_issues)
    reg.register("suggest_improvements", suggest_improvements)
    reg.register("evaluate_quality", evaluate_quality)
    return reg


@pytest.fixture
def graph_payload() -> dict:
    """Load the code review graph JSON."""
    graph_path = Path(__file__).parent.parent / "sample_graphs" / "code_review.json"
    with open(graph_path) as f:
        return json.load(f)


@pytest.fixture
def graph(graph_payload: dict, registry: ToolRegistry) -> Graph:
    """Build the graph from payload."""
    return Graph.from_dict(graph_payload, registry=registry)


class TestExtractFunctions:
    """Tests for the extract_functions tool."""

    def test_extracts_simple_functions(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        result = extract_functions(state)

        assert "functions" in result.context
        assert result.context["function_count"] == 2

        func_names = [f["name"] for f in result.context["functions"]]
        assert "greet" in func_names
        assert "add" in func_names

    def test_detects_docstrings(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        result = extract_functions(state)

        for func in result.context["functions"]:
            assert func["has_docstring"] is True

    def test_detects_missing_docstrings(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        result = extract_functions(state)

        for func in result.context["functions"]:
            assert func["has_docstring"] is False

    def test_counts_parameters(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        result = extract_functions(state)

        calc_func = next(
            f for f in result.context["functions"] if f["name"] == "calculate_something"
        )
        assert calc_func["param_count"] == 7

    def test_records_execution(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        result = extract_functions(state)

        assert len(result.history) == 1
        assert result.history[0].node_id == "extract_functions"


class TestCheckComplexity:
    """Tests for the check_complexity tool."""

    def test_calculates_complexity(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        result = check_complexity(state)

        assert "complexity" in result.context
        assert result.context["total_complexity"] > 0

    def test_high_complexity_detection(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        result = check_complexity(state)

        calc_complexity = next(
            c for c in result.context["complexity"] if c["name"] == "calculate_something"
        )
        assert calc_complexity["complexity"] > 10
        assert calc_complexity["rating"] in ("high", "very_high")

    def test_low_complexity_for_simple_code(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        state = extract_functions(state)
        result = check_complexity(state)

        for complexity in result.context["complexity"]:
            assert complexity["rating"] == "low"


class TestDetectBasicIssues:
    """Tests for the detect_basic_issues tool."""

    def test_detects_missing_docstrings(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        state = check_complexity(state)
        result = detect_basic_issues(state)

        issue_types = [i["type"] for i in result.context["issues"]]
        assert "missing_docstring" in issue_types

    def test_detects_too_many_params(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        state = check_complexity(state)
        result = detect_basic_issues(state)

        issue_types = [i["type"] for i in result.context["issues"]]
        assert "too_many_params" in issue_types

    def test_detects_high_complexity(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        state = check_complexity(state)
        result = detect_basic_issues(state)

        issue_types = [i["type"] for i in result.context["issues"]]
        assert "high_complexity" in issue_types

    def test_detects_todo_comments(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        state = check_complexity(state)
        result = detect_basic_issues(state)

        issue_types = [i["type"] for i in result.context["issues"]]
        assert "todo_comment" in issue_types

    def test_sets_default_threshold(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        state = extract_functions(state)
        state = check_complexity(state)
        result = detect_basic_issues(state)

        assert result.context["threshold"] == 70


class TestSuggestImprovements:
    """Tests for the suggest_improvements tool."""

    def test_generates_suggestions(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        state = check_complexity(state)
        state = detect_basic_issues(state)
        result = suggest_improvements(state)

        assert "suggestions" in result.context
        assert result.context["suggestion_count"] > 0

    def test_increments_iteration(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        state = check_complexity(state)
        state = detect_basic_issues(state)

        result = suggest_improvements(state)
        assert result.context["improvement_iteration"] == 1

        result = suggest_improvements(result)
        assert result.context["improvement_iteration"] == 2

    def test_applies_suggestions_progressively(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        state = extract_functions(state)
        state = check_complexity(state)
        state = detect_basic_issues(state)

        result = suggest_improvements(state)
        first_applied = len(result.context["applied_suggestions"])

        result = suggest_improvements(result)
        second_applied = len(result.context["applied_suggestions"])

        assert second_applied >= first_applied


class TestEvaluateQuality:
    """Tests for the evaluate_quality tool."""

    def test_calculates_quality_score(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        state = extract_functions(state)
        state = check_complexity(state)
        state = detect_basic_issues(state)
        state = suggest_improvements(state)
        result = evaluate_quality(state)

        assert "quality_score" in result.context
        assert 0 <= result.context["quality_score"] <= 100

    def test_assigns_grade(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        state = extract_functions(state)
        state = check_complexity(state)
        state = detect_basic_issues(state)
        state = suggest_improvements(state)
        result = evaluate_quality(state)

        assert result.context["quality_grade"] in ("A", "B", "C", "D", "F")

    def test_quality_improves_with_iterations(self) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES, "threshold": 100})
        state = extract_functions(state)
        state = check_complexity(state)
        state = detect_basic_issues(state)

        scores = []
        for _ in range(3):
            state = suggest_improvements(state)
            state = evaluate_quality(state)
            scores.append(state.context["quality_score"])

        # Score should improve with each iteration
        assert scores[1] >= scores[0]
        assert scores[2] >= scores[1]


class TestFullWorkflow:
    """Integration tests for the complete code review workflow."""

    def test_graph_loads_correctly(self, graph_payload: dict, registry: ToolRegistry) -> None:
        graph = Graph.from_dict(graph_payload, registry=registry)
        assert graph.start_node == "extract_functions"
        assert len(graph.nodes) == 5

    def test_workflow_completes_with_simple_code(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE, "threshold": 70})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        assert result.final_state.status == "completed"
        assert result.final_state.context["quality_score"] >= 70

    def test_workflow_loops_until_threshold(self, graph: Graph) -> None:
        # Use code with issues and a moderate threshold
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES, "threshold": 50})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        assert result.final_state.status == "completed"
        assert result.final_state.context["quality_score"] >= 50
        # Should have looped at least once
        assert result.final_state.context.get("improvement_iteration", 0) >= 1

    def test_workflow_extracts_functions(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        assert "functions" in result.final_state.context
        assert result.final_state.context["function_count"] == 2

    def test_workflow_detects_issues(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        assert "issues" in result.final_state.context
        assert result.final_state.context["issue_count"] > 0

    def test_workflow_generates_suggestions(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        assert "suggestions" in result.final_state.context
        assert "applied_suggestions" in result.final_state.context

    def test_workflow_produces_quality_report(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        assert "quality_report" in result.final_state.context
        report = result.final_state.context["quality_report"]
        assert "score" in report
        assert "grade" in report
        assert "breakdown" in report
        assert "metrics" in report

    def test_workflow_records_history(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        # Should have at least one history entry per node executed
        assert len(result.final_state.history) >= 5

    def test_workflow_logs_execution(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        executor = Executor(node_timeout=30.0)

        logs_collected = []
        result = executor.run(graph, state, log_hook=logs_collected.append)

        assert len(logs_collected) >= 5
        node_ids = [log.node_id for log in logs_collected]
        assert "extract_functions" in node_ids
        assert "check_complexity" in node_ids
        assert "detect_basic_issues" in node_ids
        assert "suggest_improvements" in node_ids
        assert "evaluate_quality" in node_ids

    def test_workflow_with_custom_threshold(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_WITH_ISSUES, "threshold": 90})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        assert result.final_state.status == "completed"
        # Should eventually meet the threshold
        assert result.final_state.context["quality_score"] >= 90

    def test_workflow_empty_code(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": ""})
        executor = Executor(node_timeout=30.0)
        result = executor.run(graph, state)

        assert result.final_state.status == "completed"
        assert result.final_state.context["function_count"] == 0


class TestAsyncWorkflow:
    """Async execution tests."""

    @pytest.mark.asyncio
    async def test_async_execution(self, graph: Graph) -> None:
        state = WorkflowState(context={"code": SAMPLE_CODE_SIMPLE})
        executor = Executor(node_timeout=30.0)
        result = await executor.run_async(graph, state)

        assert result.final_state.status == "completed"
        assert result.final_state.context["quality_score"] >= 70

