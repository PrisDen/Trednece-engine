# Workflow Engine

Minimal FastAPI-powered workflow/graph engine that executes typed state machines for branching review flows. Now includes log streaming and run cancellation support.

## What It Implements
- Pydantic-based shared state passed through Python or async callables.
- Graph loader with sequential, branch, and loop edges plus validation.
- Execution engine with logging, loop safeguards, per-node timeout, sync/background runs, and cancellation.
- FastAPI surfaces `/graph/create`, `/graph/run`, `/graph/state/{run_id}`, `/graph/cancel/{run_id}`.
- WebSocket streaming for live logs at `/ws/logs/{run_id}` (replays terminal statuses).
- In-memory graph/run stores with per-run locks suitable for demos and interviews.

## Folder Structure
- `engine/` – core workflow primitives (state, node, graph, executor).
- `app/` – FastAPI app, schemas, routes, dependency helpers, WebSocket routes.
- `tools/` – workflow tool implementations (code review mini-agent, etc.).
- `sample_graphs/` – example workflow JSON definitions.
- `tests/` – unit and integration tests (pytest).
- `.github/workflows/ci.yml` – GitHub Actions CI (pytest on 3.11).

## Quickstart
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## Code Review Mini-Agent Workflow

A complete sample workflow demonstrating the engine's capabilities. Located in `sample_graphs/code_review.json` with tools in `tools/code_review_mini.py`.

### Workflow Steps
1. **extract_functions** – Parse source code to extract function definitions and metadata
2. **check_complexity** – Calculate cyclomatic complexity for each function
3. **detect_basic_issues** – Identify code quality issues (missing docstrings, too many params, high complexity, etc.)
4. **suggest_improvements** – Generate actionable improvement suggestions
5. **evaluate_quality** – Compute quality score (0-100); loops back to step 4 until score ≥ threshold

### Usage
```bash
# Register the code review graph
curl -X POST http://localhost:8000/graph/create \
  -H "Content-Type: application/json" \
  -d @sample_graphs/code_review.json

# Run code review on a sample
curl -X POST http://localhost:8000/graph/run \
  -H "Content-Type: application/json" \
  -d '{
    "graph_id": "code_review_mini",
    "initial_state": {
      "code": "def foo(a, b, c, d, e, f):\n    if a > 0:\n        return b\n    return c",
      "threshold": 70
    },
    "background": false
  }'

# Retrieve run state and quality report
curl http://localhost:8000/graph/state/<run_id>
```

### Quality Score Calculation
- Base score: 100
- Deductions: errors (-10), warnings (-5), info (-2), high complexity penalty
- Bonuses: applied improvements (+5 each), iteration bonus (+8 per loop)
- Score clamped to 0-100, grades: A (90+), B (80+), C (70+), D (60+), F (<60)

## Basic Workflow Example

For simpler use cases with placeholder tools:

```json
{
  "id": "code-review-a",
  "name": "Code Review Loop",
  "start_node": "submit",
  "nodes": [
    {"id": "submit", "callable": "tools.noop"},
    {"id": "review", "callable": "tools.noop"},
    {"id": "fix", "callable": "tools.noop"},
    {"id": "approve", "callable": "tools.approve"}
  ],
  "edges": [
    {"from": "submit", "to": "review", "type": "sequential"},
    {
      "from": "review",
      "to": "approve",
      "type": "branch",
      "condition": {"expression": "context.get('issues_open', 0) == 0"}
    },
    {
      "from": "review",
      "to": "fix",
      "type": "branch",
      "condition": {"expression": "context.get('issues_open', 0) > 0"}
    },
    {
      "from": "fix",
      "to": "review",
      "type": "loop",
      "loop": {
        "max_iterations": 3,
        "until_expression": "context.get('issues_open', 0) == 0"
      }
    }
  ]
}
```

```bash
# register the graph
curl -X POST http://localhost:8000/graph/create \
  -H "Content-Type: application/json" \
  -d @code_review.json

# run with an open issue to trigger loop
curl -X POST http://localhost:8000/graph/run \
  -H "Content-Type: application/json" \
  -d '{"graph_id":"code-review-a","initial_state":{"issues_open":1},"background":false}'

# retrieve run state/logs
curl http://localhost:8000/graph/state/<run_id>

# cancel a running execution
curl -X POST http://localhost:8000/graph/cancel/<run_id>
```

### WebSocket Log Stream
```bash
websocat ws://localhost:8000/ws/logs/<run_id>
```
Messages include `{"type":"log","log":{...}}` and terminal `{"type":"status","status":"completed"|"failed"|"cancelled"}`.

## Engine Capabilities & Current Limits
- Supports sequential execution, safe expression-based branching (AST evaluator), bounded loops, per-node timeout, execution logs, background runs, and cancellations.
- WebSocket streaming for live logs during execution with terminal status replay.
- Stores graphs/runs in-memory only (no persistence layer yet).
- Loop/branch conditions rely on sandboxed expressions; DSL alternative is future work.
- Tool registry includes built-in code review tools; additional domain-specific callables can be registered on startup.

## Branching & Looping At A Glance
- **Branch edges** carry a `condition` block with either a callable name or sandboxed Python expression; first truthy edge is taken.
- **Loop edges** declare `max_iterations` and optional `until_expression`; executor enforces the iteration cap and breaks once the condition is met.
- **Sequential edges** act as defaults when no branch/loop fires, making the graph readable for reviewers.

## Future Improvements
- Add persistence and pagination for graphs/runs via SQLite or Redis.
- Expand tool registry loading (entry point discovery, dependency injection).
- Enhance WebSocket client UX and add server-sent events fallback.
- Build more contract tests for branch/loop semantics.
- Introduce role-based access control and API tokens.

## Security Notes
- Branch/loop expressions are parsed via a restricted AST evaluator (no builtins, no attribute access), but still treat inputs as untrusted; prefer a DSL for multi-tenant scenarios.
- No authentication or rate limiting is enabled; add before exposing publicly.
- In-memory stores and WebSocket streams are unauthenticated; consider auth tokens and transport security.

## Interview Defense Notes
- Emphasize Pydantic state for schema guarantees and FastAPI interop.
- Highlight data-driven graph + registry separation to hot-swap logic safely.
- Explain loop safeguards and sandboxed branching as production-ready guardrails.

