"""
src/devices/rfid_evdev.py

RFID reader skeleton: most cheap RFID readers on a kiosk SBC present as a
"keyboard wedge" HID device -- each badge swipe types the tag's digits
followed by Enter. evdev lets this driver grab() the device exclusively
so those keystrokes never leak into whatever has input focus (the kiosk
Chromium window), and reads them here as raw key events instead.

`evdev` is a hardware-group-only dependency (pyproject.toml
[tool.poetry.group.hardware]), only installed via `poetry install --with
hardware` (or always, inside docker/bridge.Dockerfile). Guarded here so a
plain `poetry install` still works on a dev machine with no evdev wheel
available -- the ImportError only surfaces in __init__, i.e. only if this
device type is actually enabled in config
(src/infrastructure/config.py RfidDeviceSettings.enabled).
"""

from __future__ import annotations

from typing import Any

from src.devices.base import Device
from src.events.bus import EventBus
from src.events.types import DeviceStatusChanged
from src.events.types import RfidTagRead
from src.infrastructure.logging.logger import log

try:
    import evdev
except ImportError:
    evdev = None

# Keys 0-9 as evdev key-code names -- the alphabet a numeric RFID UID
# types out, terminated by Enter. TODO: extend if a deployed reader also
# emits hyphens/letters (some 26-bit Wiegand-to-USB adapters do).
_DIGIT_KEYS = {f"KEY_{d}": str(d) for d in range(10)}


class RfidEvdevDevice(Device):
    """Skeleton evdev keyboard-wedge RFID reader.

    TODO before this drives real hardware: validate grab() failure modes
    (device busy, permission denied -- see docs/INSTALLATION.md's udev
    group notes), non-numeric tag alphabets, and the read loop's
    reconnection semantics across a device unplug/replug (today an
    unplug surfaces as async_read_loop() raising OSError, which the
    DeviceManager restart-with-backoff handles, but re-grabbing the same
    /dev/input/by-id path after replug is unverified on real hardware).
    """

    def __init__(self, bus: EventBus, device_path: str, name: str = "rfid") -> None:
        super().__init__(name=name, bus=bus)
        if evdev is None:
            raise ImportError(
                "evdev is not installed. Install the 'hardware' Poetry group "
                "(`poetry install --with hardware`) to enable the RFID device."
            )
        self._device_path = device_path
        self._dev: Any = None
        self._buffer = ""

    async def start(self) -> None:
        self._dev = evdev.InputDevice(self._device_path)
        self._dev.grab()  # exclusive: keystrokes never reach the kiosk browser
        self.status = "ready"
        self.bus.publish(DeviceStatusChanged(device=self.name, status="ready"))
        log.info("RFID device %r grabbed at %s.", self.name, self._device_path)

        async for event in self._dev.async_read_loop():
            if event.type != evdev.ecodes.EV_KEY or event.value != 1:  # key-down only
                continue
            key = evdev.categorize(event)
            key_name = key.keycode if isinstance(key.keycode, str) else key.keycode[0]
            if key_name == "KEY_ENTER":
                if self._buffer:
                    self.bus.publish(RfidTagRead(device=self.name, tag=self._buffer))
                self._buffer = ""
            elif key_name in _DIGIT_KEYS:
                self._buffer += _DIGIT_KEYS[key_name]
            # TODO: malformed/partial reads and the reader's own
            # idle-timeout behaviour need real hardware to validate.

    async def stop(self) -> None:
        if self._dev is not None:
            try:
                self._dev.ungrab()
            except OSError:
                pass  # already released, e.g. device unplugged
            self._dev.close()
            self._dev = None
