# Workflow Engine

Minimal FastAPI-powered workflow/graph engine that executes typed state machines for branching review flows. Now includes log streaming and run cancellation support.

## What It Implements
- Pydantic-based shared state passed through Python or async callables.
- Graph loader with sequential, branch, and loop edges plus validation.
- Execution engine with logging, loop safeguards, sync/background runs, and cancellation.
- FastAPI surfaces `/graph/create`, `/graph/run`, `/graph/state/{run_id}`, `/graph/cancel/{run_id}`.
- WebSocket streaming for live logs at `/ws/logs/{run_id}`.
- In-memory graph/run stores suitable for demos and interviews.

## Folder Structure
- `engine/` – core workflow primitives (state, node, graph, executor).
- `app/` – FastAPI app, schemas, routes, dependency helpers, WebSocket routes.
- `tests/` – unit and integration tests (pytest).
- `.github/workflows/ci.yml` – GitHub Actions CI (pytest on 3.11).

## Quickstart
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

## Sample Code-Review Workflow

`code_review.json`
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

```
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
- Supports sequential execution, safe expression-based branching, bounded loops, execution logs, background runs, and cancellations.
- WebSocket streaming for live logs during execution.
- Stores graphs/runs in-memory only (no persistence layer yet).
- Loop/branch conditions rely on sandboxed Python expressions; DSL alternative is future work.
- Tool registry ships with placeholders; real workflows should register domain-specific callables on startup.

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

## Interview Defense Notes
- Emphasize Pydantic state for schema guarantees and FastAPI interop.
- Highlight data-driven graph + registry separation to hot-swap logic safely.
- Explain loop safeguards and sandboxed branching as production-ready guardrails.

