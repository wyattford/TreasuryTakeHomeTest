"""A concurrency limit that hands free slots out by priority.

Used to share the vision model between an agent reviewing one label at their
desk and a 300-label batch running in the background: with a plain semaphore
the agent's image would queue behind every batch image already waiting. With
this gate it waits for at most the images already *being read*.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
from contextlib import asynccontextmanager

INTERACTIVE = 0
BATCH = 1


class PriorityGate:
    def __init__(self, slots: int) -> None:
        self._free = slots
        # (priority, arrival order, future) — lower sorts first; arrival
        # order keeps it first-come-first-served within a priority.
        self._waiters: list[tuple[int, int, asyncio.Future[None]]] = []
        self._arrivals = itertools.count()

    @asynccontextmanager
    async def slot(self, priority: int):
        await self._acquire(priority)
        try:
            yield
        finally:
            self._release()

    async def _acquire(self, priority: int) -> None:
        if self._free > 0 and not self._waiters:
            self._free -= 1
            return
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._arrivals), future))
        try:
            await future
        except asyncio.CancelledError:
            # Cancelled after being handed a slot but before resuming: give
            # it to the next waiter rather than leaking it. (If cancelled
            # while still waiting, the future is cancelled too and _release
            # skips it.)
            if future.done() and not future.cancelled():
                self._release()
            raise

    def _release(self) -> None:
        while self._waiters:
            _, _, future = heapq.heappop(self._waiters)
            if not future.done():
                future.set_result(None)
                return
        self._free += 1
