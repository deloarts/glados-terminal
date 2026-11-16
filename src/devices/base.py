"""
src/devices/base.py

Device base class every driver implements: rfid_evdev.py,
scanner_serial.py, mock.py. A device owns one physical (or simulated)
input, publishes events onto the shared EventBus, and tracks its own
status -- it never imports anything from src/api/ (see the
`architecture` skill's layering rule: api -> events -> devices, never the
other way).
"""

from abc import ABC
from abc import abstractmethod

from src.events.bus import EventBus
from src.events.types import DeviceStatus


class Device(ABC):
    """Base class for a hardware (or mock) device driver."""

    def __init__(self, name: str, bus: EventBus) -> None:
        self.name = name
        self.bus = bus
        self.status: DeviceStatus = "stopped"

    @abstractmethod
    async def start(self) -> None:
        """Open the device and run its read loop until cancelled. Expected
        to run forever (or until stop() cancels it) -- DeviceManager
        (manager.py) treats a start() that returns or raises as a crash
        and restarts it with backoff, same as an exception. Must publish
        its own DeviceStatusChanged("ready") once actually open; must
        never crash the daemon for a merely absent/disconnected device --
        raise/let the manager catch it and report "error" instead."""

    @abstractmethod
    async def stop(self) -> None:
        """Release the device (evdev grab, serial port, ...). Called by
        the manager after cancelling start()'s task, so must be safe to
        call whether or not start() ever completed its own setup."""
