from __future__ import annotations

"""Integration tests for FastAPI application."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def sample_graph_payload() -> dict:
    return {
        "id": "code-review-a",
        "name": "Code Review Loop",
        "start_node": "submit",
        "nodes": [
            {"id": "submit", "callable": "tools.noop"},
            {"id": "review", "callable": "tools.noop"},
            {"id": "approve", "callable": "tools.approve"},
        ],
        "edges": [
            {"from": "submit", "to": "review", "type": "sequential"},
            {
                "from": "review",
                "to": "approve",
                "type": "branch",
                "condition": {"expression": "context.get('issues', 0) == 0"},
            },
        ],
    }


def test_create_graph(client: TestClient) -> None:
    response = client.post("/graph/create", json=sample_graph_payload())
    assert response.status_code == 201
    assert response.json()["graph_id"] == "code-review-a"


def test_run_and_state_flow(client: TestClient) -> None:
    client.post("/graph/create", json=sample_graph_payload())
    run_resp = client.post(
        "/graph/run",
        json={"graph_id": "code-review-a", "initial_state": {"issues": 0}, "background": False},
    )
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]

    state_resp = client.get(f"/graph/state/{run_id}")
    assert state_resp.status_code == 200
    payload = state_resp.json()
    assert payload["status"] == "completed"
    assert payload["graph_id"] == "code-review-a"


def test_run_missing_graph_returns_404(client: TestClient) -> None:
    response = client.post("/graph/run", json={"graph_id": "missing", "initial_state": {}, "background": False})
    assert response.status_code == 404

