from __future__ import annotations

"""Tool registry managing callable nodes."""

from typing import Dict

from engine.node import NodeCallable


class ToolRegistry:
    """Container responsible for storing workflow node callables."""

    def __init__(self) -> None:
        self._tools: Dict[str, NodeCallable] = {}

    def register(self, name: str, func: NodeCallable) -> None:
        """Register a callable under the provided name."""

        if name in self._tools:
            raise ValueError(f"Tool '{name}' is already registered.")
        self._tools[name] = func

    def get(self, name: str) -> NodeCallable:
        """Retrieve a registered callable by name."""

        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Tool '{name}' is not registered.") from exc

    def has(self, name: str) -> bool:
        """Check whether a tool name is already registered."""

        return name in self._tools

    def unregister(self, name: str) -> None:
        """Remove a registered tool."""

        self._tools.pop(name, None)


__all__ = ["ToolRegistry"]

