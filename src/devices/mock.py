"""
src/devices/mock.py

Fully working device used by the debug endpoint (src/api/debug.py, only
mounted when DEBUG=true) and by tests: it never touches real hardware,
just reports "ready" and sits idle until asked to emit a simulated event.
Lets frontend development and the test suite exercise the whole event
path (device -> bus -> /ws/events) without an RFID reader or scanner
attached.
"""

import asyncio

from src.devices.base import Device
from src.events.bus import EventBus
from src.events.types import DeviceStatusChanged
from src.events.types import RfidTagRead
from src.events.types import ScannerRead


class MockDevice(Device):
    def __init__(self, bus: EventBus, name: str = "mock") -> None:
        super().__init__(name=name, bus=bus)
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self._stop_event = asyncio.Event()  # fresh event each (re)start
        self.status = "ready"
        self.bus.publish(DeviceStatusChanged(device=self.name, status="ready"))
        await self._stop_event.wait()

    async def stop(self) -> None:
        self._stop_event.set()

    def simulate_rfid(self, tag: str) -> None:
        """Injects a simulated RfidTagRead, as if a badge had been read."""
        self.bus.publish(RfidTagRead(device=self.name, tag=tag))

    def simulate_scan(self, code: str, symbology: str | None = None) -> None:
        """Injects a simulated ScannerRead, as if a barcode had been scanned."""
        self.bus.publish(ScannerRead(device=self.name, code=code, symbology=symbology))
