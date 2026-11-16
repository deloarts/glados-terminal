"""
src/devices/scanner_serial.py

QR/barcode scanner skeleton: most USB scanners on a kiosk SBC present as
a plain serial (CDC-ACM) device that streams one line per scan,
terminated by CR/LF. pyserial-asyncio gives an asyncio-native line reader
-- deliberately a different integration style than rfid_evdev.py's evdev
keyboard-wedge approach, because the two device families behave
differently at the OS level (see the `architecture` skill).

`pyserial-asyncio` (import name `serial_asyncio`) is a hardware-group-only
dependency (pyproject.toml [tool.poetry.group.hardware]), guarded here the
same way as rfid_evdev.py: importing this module never fails, only
instantiating the device does, and only if it's actually enabled.
"""

from __future__ import annotations

from typing import Any

from src.devices.base import Device
from src.events.bus import EventBus
from src.events.types import DeviceStatusChanged
from src.events.types import ScannerRead
from src.infrastructure.logging.logger import log

try:
    import serial_asyncio
except ImportError:
    serial_asyncio = None


class ScannerSerialDevice(Device):
    """Skeleton line-oriented serial scanner reader.

    TODO before this drives real hardware: symbology prefix/suffix bytes
    some scanners emit around the payload, partial reads across a USB
    re-enumeration, and non-UTF-8 payloads (today decoded with
    errors="replace", which is a safe default but silently mangles a
    genuinely non-UTF-8 code rather than surfacing it).
    """

    def __init__(
        self, bus: EventBus, device_path: str, baud_rate: int = 9600, name: str = "scanner"
    ) -> None:
        super().__init__(name=name, bus=bus)
        if serial_asyncio is None:
            raise ImportError(
                "pyserial-asyncio is not installed. Install the 'hardware' Poetry "
                "group (`poetry install --with hardware`) to enable the scanner device."
            )
        self._device_path = device_path
        self._baud_rate = baud_rate
        self._transport: Any = None

    async def start(self) -> None:
        reader, transport = await serial_asyncio.open_serial_connection(
            url=self._device_path, baudrate=self._baud_rate
        )
        self._transport = transport
        self.status = "ready"
        self.bus.publish(DeviceStatusChanged(device=self.name, status="ready"))
        log.info("Scanner device %r opened at %s.", self.name, self._device_path)

        while True:
            line = await reader.readline()
            if not line:
                break  # EOF: port closed/unplugged, let the manager restart us
            code = line.decode("utf-8", errors="replace").strip()
            if code:
                self.bus.publish(ScannerRead(device=self.name, code=code))
            # TODO: see the class docstring's TODO list.

    async def stop(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None
