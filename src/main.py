"""
src/main.py

Composition root: builds the config, event bus, device manager (wiring in
whichever devices are enabled), the device identity store, the display
controller and device reader, and the FastAPI app. `poetry run uvicorn
src.main:app --reload --port 8600` for local dev (see
docs/DEVELOPMENT.md); the module-level `app` below is what uvicorn
imports, both there and in the Docker image (docker/bridge.Dockerfile).

This process owns local hardware and stores this device's credentials
-- no business logic, no auth checks, and
it must never bind anywhere but 127.0.0.1 outside of the Docker Compose
setup, where the loopback guarantee moves to the compose port mapping
instead (see docs/INSTALLATION.md). See CLAUDE.md's hard rules.
"""

from pathlib import Path

from fastapi import FastAPI

from src.api.app import create_app
from src.devices.base import Device
from src.devices.manager import DeviceManager
from src.devices.mock import MockDevice
from src.events.bus import EventBus
from src.host.cec import CecClient
from src.host.device_info import DeviceInfoReader
from src.host.display import DisplayController
from src.host.sway import SwayClient
from src.identity.store import IdentityStore
from src.infrastructure.config import cfg
from src.infrastructure.logging.logger import log


def _build_devices(bus: EventBus) -> list[Device]:
    """Wires in whichever devices are enabled in config. Each device type
    guards its own hardware import (see rfid_evdev.py/scanner_serial.py)
    -- a device that's enabled but whose driver library isn't installed
    fails loudly here, at startup, rather than the daemon starting and
    silently missing hardware."""
    devices: list[Device] = []

    if cfg.mock.enabled:
        devices.append(MockDevice(bus=bus))

    if cfg.rfid.enabled:
        from src.devices.rfid_evdev import RfidEvdevDevice

        devices.append(RfidEvdevDevice(bus=bus, device_path=cfg.rfid.device_path))

    if cfg.scanner.enabled:
        from src.devices.scanner_serial import ScannerSerialDevice

        devices.append(
            ScannerSerialDevice(
                bus=bus, device_path=cfg.scanner.device_path, baud_rate=cfg.scanner.baud_rate
            )
        )

    if not devices:
        log.warning("No devices enabled in config -- the bridge will report an empty device list.")

    return devices


def build_app() -> FastAPI:
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=_build_devices(bus))
    identity = IdentityStore(state_dir=Path(cfg.identity.state_dir), api_key=cfg.identity.api_key)
    display = DisplayController(
        sway=SwayClient(socket_dir=Path(cfg.system.sway_socket_dir)), cec=CecClient()
    )
    device_info = DeviceInfoReader(
        os_release_path=Path(cfg.system.os_release_path),
        hostname_path=Path(cfg.system.hostname_path),
    )
    return create_app(
        bus=bus, manager=manager, identity=identity, display=display, device_info=device_info
    )


app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host=cfg.bridge.host, port=cfg.bridge.port, reload=cfg.debug)
