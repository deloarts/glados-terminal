"""
src/events/bus.py

Minimal asyncio pub/sub event bus. Each subscriber gets its own bounded
queue; publishing is fire-and-forget per subscriber (put_nowait), so one
slow or disconnected consumer (a stalled WebSocket write, for instance)
can never block delivery to the others. A full queue drops the oldest
event for that subscriber only, and logs it -- a stalled subscriber
should catch up on recent state, not stay stuck replaying stale events,
and the publisher must never be backpressured by the slowest listener.
"""

import asyncio
from collections.abc import AsyncIterator

from src.events.types import BridgeEvent
from src.infrastructure.logging.logger import log

DEFAULT_QUEUE_MAXSIZE = 100


class Subscription:
    """One subscriber's queue plus an async-iterator view over it. Created
    via EventBus.subscribe(), never directly."""

    def __init__(self, maxsize: int = DEFAULT_QUEUE_MAXSIZE) -> None:
        self._queue: asyncio.Queue[BridgeEvent] = asyncio.Queue(maxsize=maxsize)

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def publish(self, event: BridgeEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop the oldest, not the newest -- a caught-up subscriber is
            # more useful than one stuck replaying stale events.
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            log.warning("Event bus: subscriber queue full, dropped oldest event.")
            try:
                self._queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # lost a race with another publisher; not worth retrying further

    async def get(self) -> BridgeEvent:
        return await self._queue.get()

    async def __aiter__(self) -> AsyncIterator[BridgeEvent]:
        while True:
            yield await self.get()


class EventBus:
    """Async pub/sub. Subscribe for an async-iterable of events; publish
    fans an event out to every currently-subscribed queue."""

    def __init__(self) -> None:
        self._subscribers: set[Subscription] = set()

    def subscribe(self) -> Subscription:
        sub = Subscription()
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subscribers.discard(sub)

    def publish(self, event: BridgeEvent) -> None:
        for sub in list(self._subscribers):
            sub.publish(event)
