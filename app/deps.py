from __future__ import annotations

"""Dependency helpers for FastAPI routes."""

from fastapi import Request


def get_graph_store(request: Request):
    """Return the in-memory graph store."""

    return request.app.state.graph_store


def get_run_store(request: Request):
    """Return the in-memory run store."""

    return request.app.state.run_store


def get_tool_registry(request: Request):
    """Return the tool registry."""

    return request.app.state.tool_registry


def get_executor(request: Request):
    """Return the workflow executor."""

    return request.app.state.executor


__all__ = [
    "get_executor",
    "get_graph_store",
    "get_run_store",
    "get_tool_registry",
]

