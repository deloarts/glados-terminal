"""
src/devices/manager.py

Owns every configured Device (src/devices/base.py), starts them with the
FastAPI app's lifespan (src/api/app.py), and supervises each one: a
device's start() runs as its own background task, and a task that ends --
because the driver's read loop raised, e.g. the RFID reader was unplugged
-- is restarted with exponential backoff rather than taking the whole
daemon down. Emits device.status events onto the bus on every state
transition so the frontend can show "reader offline" without the bridge
itself crashing -- a hard project rule, see CLAUDE.md.
"""

import asyncio

from src.devices.base import Device
from src.events.bus import EventBus
from src.events.types import DeviceStatus
from src.events.types import DeviceStatusChanged
from src.infrastructure.logging.logger import log

_INITIAL_BACKOFF_SECONDS = 1.0
_MAX_BACKOFF_SECONDS = 30.0


class DeviceManager:
    """Starts/stops/supervises the configured set of devices."""

    def __init__(self, bus: EventBus, devices: list[Device]) -> None:
        self._bus = bus
        self._devices = devices
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def devices(self) -> list[Device]:
        return self._devices

    async def start(self) -> None:
        """Kicks off a supervisor task per device and returns immediately
        -- does NOT wait for devices to report ready. Blocking daemon
        startup on hardware would violate the same "never let a device
        failure stall the app" rule this manager exists to enforce."""
        for device in self._devices:
            self._tasks[device.name] = asyncio.create_task(
                self._supervise(device), name=f"device:{device.name}"
            )

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        for device in self._devices:
            try:
                await device.stop()
            except Exception:
                log.exception("Device %r raised while stopping.", device.name)

    async def _supervise(self, device: Device) -> None:
        """Runs device.start() in a restart loop with exponential backoff.
        A device that keeps failing degrades the daemon's view of that one
        device only -- see the module docstring."""
        backoff = _INITIAL_BACKOFF_SECONDS
        while True:
            self._set_status(device, "starting")
            try:
                await device.start()
                # start() is expected to run forever (see base.py); a
                # normal return is treated the same as a crash below.
                log.warning("Device %r start() returned; restarting.", device.name)
                self._set_status(device, "error", detail="device loop exited unexpectedly")
            except asyncio.CancelledError:
                self._set_status(device, "stopped")
                raise
            except Exception as exc:
                log.exception("Device %r crashed: %s", device.name, exc)
                self._set_status(device, "error", detail=str(exc))

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

    def _set_status(self, device: Device, status: DeviceStatus, detail: str | None = None) -> None:
        device.status = status
        self._bus.publish(DeviceStatusChanged(device=device.name, status=status, detail=detail))
