"""
tests/test_event_bus.py

Coverage for the event bus's fan-out and slow-consumer isolation
(src/events/bus.py): every subscriber gets its own queue, so one
subscriber that never reads must not stop another from receiving events,
and a full queue must drop the oldest event rather than block or raise.
"""

import asyncio

from src.events.bus import DEFAULT_QUEUE_MAXSIZE
from src.events.bus import EventBus
from src.events.types import RfidTagRead


async def test_multiple_subscribers_all_receive_the_event() -> None:
    bus = EventBus()
    sub_a = bus.subscribe()
    sub_b = bus.subscribe()

    event = RfidTagRead(device="rfid", tag="1234")
    bus.publish(event)

    received_a = await asyncio.wait_for(sub_a.get(), timeout=1)
    received_b = await asyncio.wait_for(sub_b.get(), timeout=1)
    assert received_a is event
    assert received_b is event


async def test_slow_subscriber_does_not_block_or_drop_for_others() -> None:
    bus = EventBus()
    slow = bus.subscribe()  # never read from in this test
    fast = bus.subscribe()

    received: list[str] = []
    for i in range(DEFAULT_QUEUE_MAXSIZE * 2):  # far past one subscriber's queue size
        bus.publish(RfidTagRead(device="rfid", tag=str(i)))
        event = await asyncio.wait_for(fast.get(), timeout=1)
        assert isinstance(event, RfidTagRead)
        received.append(event.tag)

    assert received == [str(i) for i in range(DEFAULT_QUEUE_MAXSIZE * 2)]  # fast lost nothing
    assert slow.queue_size == DEFAULT_QUEUE_MAXSIZE  # slow's own queue filled, isolated to it


async def test_full_queue_drops_oldest_without_raising() -> None:
    bus = EventBus()
    sub = bus.subscribe()

    for i in range(DEFAULT_QUEUE_MAXSIZE + 10):
        bus.publish(RfidTagRead(device="rfid", tag=str(i)))  # must never raise/block

    assert sub.queue_size == DEFAULT_QUEUE_MAXSIZE
    oldest_remaining = await asyncio.wait_for(sub.get(), timeout=1)
    assert isinstance(oldest_remaining, RfidTagRead)
    assert oldest_remaining.tag == "10"  # tags 0-9 were dropped to keep the newest 100


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    bus.unsubscribe(sub)

    bus.publish(RfidTagRead(device="rfid", tag="1234"))

    assert sub.queue_size == 0
