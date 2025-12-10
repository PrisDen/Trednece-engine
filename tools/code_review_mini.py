"""Code Review Mini-Agent workflow tools.

Pure rule-based tools for extracting functions, checking complexity,
detecting issues, suggesting improvements, and evaluating code quality.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from engine.state import WorkflowState


def extract_functions(state: WorkflowState) -> WorkflowState:
    """Extract function definitions from the source code.
    
    Expects state.context['code'] to contain the source code string.
    Sets state.context['functions'] with extracted function metadata.
    """
    code = state.context.get("code", "")
    
    # Simple regex-based function extraction for Python code
    # Matches: def function_name(params): or async def function_name(params):
    pattern = r"(?P<async>async\s+)?def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*(?:->\s*(?P<return_type>[^:]+))?\s*:"
    
    functions: List[Dict[str, Any]] = []
    lines = code.split("\n")
    
    for match in re.finditer(pattern, code):
        func_name = match.group("name")
        params = match.group("params").strip()
        is_async = bool(match.group("async"))
        return_type = match.group("return_type")
        
        # Find the line number
        start_pos = match.start()
        line_num = code[:start_pos].count("\n") + 1
        
        # Extract function body (simple heuristic: until next def or end)
        func_start_line = line_num - 1
        func_lines = []
        indent_level = None
        
        for i, line in enumerate(lines[func_start_line:], start=func_start_line):
            if i == func_start_line:
                func_lines.append(line)
                continue
            
            # Determine base indent from first non-empty body line
            stripped = line.lstrip()
            if stripped and indent_level is None:
                indent_level = len(line) - len(stripped)
            
            # Check if we've exited the function
            if stripped and not line.startswith(" " * (indent_level or 4)) and i > func_start_line:
                if stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("class "):
                    break
            
            func_lines.append(line)
        
        # Remove trailing empty lines
        while func_lines and not func_lines[-1].strip():
            func_lines.pop()
        
        func_body = "\n".join(func_lines)
        
        # Check for docstring
        docstring_match = re.search(r'^\s*"""([^"]*)"""', func_body[func_body.find(":") + 1:], re.MULTILINE)
        has_docstring = docstring_match is not None
        
        # Parse parameters
        param_list = []
        if params:
            for p in params.split(","):
                p = p.strip()
                if p and p not in ("self", "cls"):
                    param_list.append(p)
        
        functions.append({
            "name": func_name,
            "line": line_num,
            "params": param_list,
            "param_count": len(param_list),
            "is_async": is_async,
            "return_type": return_type.strip() if return_type else None,
            "has_docstring": has_docstring,
            "body": func_body,
            "line_count": len(func_lines),
        })
    
    state.context["functions"] = functions
    state.context["function_count"] = len(functions)
    
    state.record(
        node_id="extract_functions",
        message=f"Extracted {len(functions)} function(s) from source code",
        data={"function_names": [f["name"] for f in functions]},
    )
    
    return state


def check_complexity(state: WorkflowState) -> WorkflowState:
    """Calculate cyclomatic complexity for extracted functions.
    
    Uses a simplified complexity metric based on:
    - Number of if/elif/else statements
    - Number of for/while loops
    - Number of try/except blocks
    - Number of and/or operators
    """
    functions = state.context.get("functions", [])
    
    # Patterns that increase complexity
    complexity_patterns = [
        (r"\bif\b", 1),
        (r"\belif\b", 1),
        (r"\belse\b", 1),
        (r"\bfor\b", 1),
        (r"\bwhile\b", 1),
        (r"\btry\b", 1),
        (r"\bexcept\b", 1),
        (r"\band\b", 1),
        (r"\bor\b", 1),
        (r"\breturn\b", 1),  # Multiple returns indicate branching
    ]
    
    complexity_results: List[Dict[str, Any]] = []
    total_complexity = 0
    
    for func in functions:
        body = func.get("body", "")
        complexity = 1  # Base complexity
        
        breakdown = {}
        for pattern, weight in complexity_patterns:
            count = len(re.findall(pattern, body))
            if count > 0:
                complexity += count * weight
                pattern_name = pattern.replace(r"\b", "").strip()
                breakdown[pattern_name] = count
        
        # Adjust for multiple returns (only count additional returns)
        if breakdown.get("return", 0) > 1:
            complexity -= 1  # Don't double-count the expected single return
        
        func_result = {
            "name": func["name"],
            "complexity": complexity,
            "breakdown": breakdown,
            "rating": _complexity_rating(complexity),
        }
        complexity_results.append(func_result)
        total_complexity += complexity
    
    avg_complexity = total_complexity / len(functions) if functions else 0
    
    state.context["complexity"] = complexity_results
    state.context["total_complexity"] = total_complexity
    state.context["avg_complexity"] = round(avg_complexity, 2)
    
    state.record(
        node_id="check_complexity",
        message=f"Analyzed complexity for {len(functions)} function(s). Average: {avg_complexity:.2f}",
        data={
            "total_complexity": total_complexity,
            "avg_complexity": avg_complexity,
            "high_complexity_functions": [r["name"] for r in complexity_results if r["complexity"] > 10],
        },
    )
    
    return state


def _complexity_rating(complexity: int) -> str:
    """Return a human-readable complexity rating."""
    if complexity <= 5:
        return "low"
    elif complexity <= 10:
        return "moderate"
    elif complexity <= 20:
        return "high"
    else:
        return "very_high"


def detect_basic_issues(state: WorkflowState) -> WorkflowState:
    """Detect common code issues.
    
    Checks for:
    - Missing docstrings
    - Long lines (> 88 chars)
    - Too many parameters (> 5)
    - Long functions (> 50 lines)
    - High complexity (> 10)
    - Missing type hints
    - Unused variables (simple heuristic)
    """
    functions = state.context.get("functions", [])
    code = state.context.get("code", "")
    complexity_results = state.context.get("complexity", [])
    
    issues: List[Dict[str, Any]] = []
    
    # Map complexity by function name for lookup
    complexity_map = {c["name"]: c["complexity"] for c in complexity_results}
    
    for func in functions:
        func_name = func["name"]
        
        # Issue: Missing docstring
        if not func.get("has_docstring"):
            issues.append({
                "type": "missing_docstring",
                "function": func_name,
                "line": func["line"],
                "severity": "warning",
                "message": f"Function '{func_name}' is missing a docstring",
            })
        
        # Issue: Too many parameters
        if func.get("param_count", 0) > 5:
            issues.append({
                "type": "too_many_params",
                "function": func_name,
                "line": func["line"],
                "severity": "warning",
                "message": f"Function '{func_name}' has {func['param_count']} parameters (recommended: <= 5)",
            })
        
        # Issue: Long function
        if func.get("line_count", 0) > 50:
            issues.append({
                "type": "long_function",
                "function": func_name,
                "line": func["line"],
                "severity": "warning",
                "message": f"Function '{func_name}' is {func['line_count']} lines long (recommended: <= 50)",
            })
        
        # Issue: High complexity
        func_complexity = complexity_map.get(func_name, 0)
        if func_complexity > 10:
            issues.append({
                "type": "high_complexity",
                "function": func_name,
                "line": func["line"],
                "severity": "error",
                "message": f"Function '{func_name}' has complexity {func_complexity} (recommended: <= 10)",
            })
        
        # Issue: Missing return type hint
        if func.get("return_type") is None:
            issues.append({
                "type": "missing_return_type",
                "function": func_name,
                "line": func["line"],
                "severity": "info",
                "message": f"Function '{func_name}' is missing return type annotation",
            })
    
    # Check for long lines in entire code
    lines = code.split("\n")
    long_lines = []
    for i, line in enumerate(lines, start=1):
        if len(line) > 88:
            long_lines.append(i)
            if len(long_lines) <= 5:  # Limit reported issues
                issues.append({
                    "type": "long_line",
                    "line": i,
                    "severity": "info",
                    "message": f"Line {i} exceeds 88 characters ({len(line)} chars)",
                })
    
    # Check for TODO/FIXME comments
    todo_pattern = r"#\s*(TODO|FIXME|XXX|HACK)[\s:]+(.+)"
    for match in re.finditer(todo_pattern, code, re.IGNORECASE):
        line_num = code[:match.start()].count("\n") + 1
        tag = match.group(1).upper()
        issues.append({
            "type": "todo_comment",
            "line": line_num,
            "severity": "info",
            "message": f"{tag} found at line {line_num}: {match.group(2).strip()[:50]}",
        })
    
    # Categorize issues by severity
    issue_counts = {
        "error": len([i for i in issues if i["severity"] == "error"]),
        "warning": len([i for i in issues if i["severity"] == "warning"]),
        "info": len([i for i in issues if i["severity"] == "info"]),
    }
    
    state.context["issues"] = issues
    state.context["issue_count"] = len(issues)
    state.context["issue_counts"] = issue_counts
    
    # Initialize improvement tracking if not present
    if "improvement_iteration" not in state.context:
        state.context["improvement_iteration"] = 0
    if "applied_suggestions" not in state.context:
        state.context["applied_suggestions"] = []
    
    # Set default threshold if not provided
    if "threshold" not in state.context:
        state.context["threshold"] = 70
    
    state.record(
        node_id="detect_basic_issues",
        message=f"Detected {len(issues)} issue(s): {issue_counts['error']} errors, {issue_counts['warning']} warnings, {issue_counts['info']} info",
        data={"issue_counts": issue_counts, "issues": issues},
    )
    
    return state


def suggest_improvements(state: WorkflowState) -> WorkflowState:
    """Generate improvement suggestions based on detected issues.
    
    Each iteration simulates applying improvements to reduce issues.
    """
    issues = state.context.get("issues", [])
    iteration = state.context.get("improvement_iteration", 0)
    applied = state.context.get("applied_suggestions", [])
    
    suggestions: List[Dict[str, Any]] = []
    
    # Generate suggestions based on issue types
    suggestion_templates = {
        "missing_docstring": {
            "action": "Add a docstring describing the function's purpose, parameters, and return value",
            "impact": 5,
            "category": "documentation",
        },
        "too_many_params": {
            "action": "Consider using a configuration object or breaking down the function",
            "impact": 8,
            "category": "design",
        },
        "long_function": {
            "action": "Refactor into smaller, focused functions with single responsibilities",
            "impact": 10,
            "category": "design",
        },
        "high_complexity": {
            "action": "Simplify control flow, extract helper methods, or use early returns",
            "impact": 12,
            "category": "design",
        },
        "missing_return_type": {
            "action": "Add return type annotation for better code clarity",
            "impact": 3,
            "category": "typing",
        },
        "long_line": {
            "action": "Break long lines using proper line continuation or reformatting",
            "impact": 2,
            "category": "style",
        },
        "todo_comment": {
            "action": "Address the TODO item or create a tracked issue",
            "impact": 4,
            "category": "maintenance",
        },
    }
    
    # Generate suggestions for remaining issues
    seen_types = set()
    for issue in issues:
        issue_type = issue["type"]
        
        # Skip if we've already suggested for this issue type in previous iterations
        suggestion_key = f"{issue_type}:{issue.get('function', '')}:{issue.get('line', '')}"
        if suggestion_key in applied:
            continue
        
        # Avoid duplicate suggestions for same type in same iteration
        if issue_type in seen_types:
            continue
        seen_types.add(issue_type)
        
        template = suggestion_templates.get(issue_type, {
            "action": f"Review and address the {issue_type.replace('_', ' ')} issue",
            "impact": 3,
            "category": "general",
        })
        
        suggestion = {
            "id": f"suggestion_{len(suggestions) + 1}_{iteration}",
            "issue_type": issue_type,
            "function": issue.get("function"),
            "line": issue.get("line"),
            "action": template["action"],
            "impact": template["impact"],
            "category": template["category"],
            "original_issue": issue["message"],
        }
        suggestions.append(suggestion)
    
    # Simulate applying some suggestions (more each iteration)
    # This creates the gradual improvement effect
    suggestions_to_apply = min(len(suggestions), 2 + iteration)
    newly_applied = []
    
    for i, suggestion in enumerate(suggestions[:suggestions_to_apply]):
        suggestion_key = f"{suggestion['issue_type']}:{suggestion.get('function', '')}:{suggestion.get('line', '')}"
        if suggestion_key not in applied:
            newly_applied.append(suggestion_key)
            suggestion["applied"] = True
        else:
            suggestion["applied"] = False
    
    # Update state
    state.context["suggestions"] = suggestions
    state.context["suggestion_count"] = len(suggestions)
    state.context["applied_suggestions"] = applied + newly_applied
    state.context["improvement_iteration"] = iteration + 1
    state.context["newly_applied_count"] = len(newly_applied)
    
    # Calculate improvement impact
    total_impact = sum(s["impact"] for s in suggestions if s.get("applied"))
    state.context["iteration_impact"] = total_impact
    
    state.record(
        node_id="suggest_improvements",
        message=f"Iteration {iteration + 1}: Generated {len(suggestions)} suggestion(s), applied {len(newly_applied)}",
        data={
            "iteration": iteration + 1,
            "suggestions": suggestions,
            "newly_applied": newly_applied,
            "total_impact": total_impact,
        },
    )
    
    return state


def evaluate_quality(state: WorkflowState) -> WorkflowState:
    """Evaluate overall code quality and compute quality score.
    
    Score calculation:
    - Base score: 100
    - Deductions for issues (errors: -10, warnings: -5, info: -2)
    - Bonus for applied improvements
    """
    issue_counts = state.context.get("issue_counts", {"error": 0, "warning": 0, "info": 0})
    issues = state.context.get("issues", [])
    applied = state.context.get("applied_suggestions", [])
    functions = state.context.get("functions", [])
    avg_complexity = state.context.get("avg_complexity", 0)
    iteration = state.context.get("improvement_iteration", 1)
    threshold = state.context.get("threshold", 70)
    
    # Start with base score
    base_score = 100
    
    # Calculate deductions based on issues
    error_penalty = issue_counts.get("error", 0) * 10
    warning_penalty = issue_counts.get("warning", 0) * 5
    info_penalty = issue_counts.get("info", 0) * 2
    
    total_penalty = error_penalty + warning_penalty + info_penalty
    
    # Bonus for applied improvements (simulates fixing issues)
    # Each iteration, more improvements are "applied" which increases the score
    improvement_bonus = len(applied) * 5
    
    # Additional bonus per iteration (simulates progressive improvement)
    iteration_bonus = iteration * 8
    
    # Complexity penalty
    complexity_penalty = 0
    if avg_complexity > 10:
        complexity_penalty = int((avg_complexity - 10) * 2)
    
    # Calculate final score
    raw_score = base_score - total_penalty + improvement_bonus + iteration_bonus - complexity_penalty
    
    # Clamp score to 0-100
    quality_score = max(0, min(100, raw_score))
    
    # Determine quality grade
    if quality_score >= 90:
        grade = "A"
    elif quality_score >= 80:
        grade = "B"
    elif quality_score >= 70:
        grade = "C"
    elif quality_score >= 60:
        grade = "D"
    else:
        grade = "F"
    
    # Determine if threshold is met
    meets_threshold = quality_score >= threshold
    
    # Build quality report
    quality_report = {
        "score": quality_score,
        "grade": grade,
        "threshold": threshold,
        "meets_threshold": meets_threshold,
        "breakdown": {
            "base_score": base_score,
            "error_penalty": -error_penalty,
            "warning_penalty": -warning_penalty,
            "info_penalty": -info_penalty,
            "complexity_penalty": -complexity_penalty,
            "improvement_bonus": improvement_bonus,
            "iteration_bonus": iteration_bonus,
        },
        "metrics": {
            "function_count": len(functions),
            "total_issues": len(issues),
            "applied_improvements": len(applied),
            "iterations": iteration,
            "avg_complexity": avg_complexity,
        },
    }
    
    state.context["quality_score"] = quality_score
    state.context["quality_grade"] = grade
    state.context["quality_report"] = quality_report
    state.context["meets_threshold"] = meets_threshold
    
    status_msg = "PASSED" if meets_threshold else f"NEEDS IMPROVEMENT (target: {threshold})"
    
    state.record(
        node_id="evaluate_quality",
        message=f"Quality score: {quality_score}/100 (Grade: {grade}) - {status_msg}",
        data=quality_report,
    )
    
    return state


__all__ = [
    "extract_functions",
    "check_complexity",
    "detect_basic_issues",
    "suggest_improvements",
    "evaluate_quality",
]

