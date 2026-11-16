"""
tests/test_mock_device_manager.py

Coverage for the mock device driven through DeviceManager's lifecycle
(src/devices/manager.py, src/devices/mock.py): start -> ready, status
events published on the bus in order, stop -> stopped, clean shutdown.
"""

import asyncio

from src.devices.manager import DeviceManager
from src.devices.mock import MockDevice
from src.events.bus import EventBus
from src.events.types import DeviceStatusChanged


async def _wait_until(predicate, timeout: float = 1.0) -> None:  # type: ignore[no-untyped-def]
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(_poll(), timeout=timeout)


async def _drain(sub, timeout: float = 0.2) -> list:  # type: ignore[no-untyped-def]
    events = []
    while True:
        try:
            events.append(await asyncio.wait_for(sub.get(), timeout=timeout))
        except TimeoutError:
            return events


async def test_mock_device_becomes_ready_and_publishes_status_in_order() -> None:
    bus = EventBus()
    sub = bus.subscribe()
    mock = MockDevice(bus=bus, name="mock")
    manager = DeviceManager(bus=bus, devices=[mock])

    await manager.start()
    await _wait_until(lambda: mock.status == "ready")

    events = await _drain(sub)
    statuses = [e.status for e in events if isinstance(e, DeviceStatusChanged)]
    assert statuses == ["starting", "ready"]

    await manager.stop()
    assert mock.status == "stopped"


async def test_manager_reports_devices_and_stop_is_idempotent() -> None:
    bus = EventBus()
    mock = MockDevice(bus=bus, name="mock")
    manager = DeviceManager(bus=bus, devices=[mock])

    await manager.start()
    await _wait_until(lambda: mock.status == "ready")

    assert manager.devices == [mock]

    await manager.stop()
    await manager.stop()  # must not raise on a second stop
    assert mock.status == "stopped"


async def test_manager_with_no_devices_starts_and_stops_cleanly() -> None:
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])

    await manager.start()
    await manager.stop()

    assert manager.devices == []
