from __future__ import annotations

"""Simple WebSocket log streaming manager."""

import asyncio
from collections import defaultdict
from typing import Any, DefaultDict, Dict, List

LogMessage = Dict[str, Any]


class LogStreamManager:
    """Tracks subscribers interested in run log updates."""

    def __init__(self) -> None:
        self._subscribers: DefaultDict[str, List[asyncio.Queue[LogMessage]]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the asyncio loop used to deliver messages."""

        self._loop = loop

    def register(self, run_id: str) -> asyncio.Queue[LogMessage]:
        """Register a subscriber queue for a run."""

        queue: asyncio.Queue[LogMessage] = asyncio.Queue()
        self._subscribers[run_id].append(queue)
        return queue

    def unregister(self, run_id: str, queue: asyncio.Queue[LogMessage]) -> None:
        """Unregister a subscriber queue."""

        subscribers = self._subscribers.get(run_id)
        if not subscribers:
            return
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            self._subscribers.pop(run_id, None)

    def publish(self, run_id: str, message: LogMessage) -> None:
        """Publish a message to all subscribers."""

        if not self._loop:
            return
        for queue in list(self._subscribers.get(run_id, [])):
            asyncio.run_coroutine_threadsafe(queue.put(message), self._loop)


__all__ = ["LogStreamManager", "LogMessage"]

