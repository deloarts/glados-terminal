"""
tests/test_debug_simulate.py

Coverage for POST /debug/simulate (src/api/debug.py) -- only reachable
when DEBUG=true, injects a simulated device event through the mock device
so the event path can be exercised end-to-end without hardware.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.devices.manager import DeviceManager
from src.devices.mock import MockDevice
from src.events.bus import EventBus
from src.infrastructure.config import cfg


def test_simulate_rfid_reaches_a_connected_websocket_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "debug", True)
    bus = EventBus()
    mock = MockDevice(bus=bus, name="mock")
    manager = DeviceManager(bus=bus, devices=[mock])
    app = create_app(bus=bus, manager=manager)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as ws:
            response = client.post("/debug/simulate", json={"kind": "rfid", "value": "abc123"})
            assert response.status_code == 202
            message = ws.receive_json()

    assert message["type"] == "rfid.tag_read"
    assert message["device"] == "mock"
    assert message["data"] == {"tag": "abc123"}


def test_simulate_scanner_reaches_a_connected_websocket_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "debug", True)
    bus = EventBus()
    mock = MockDevice(bus=bus, name="mock")
    manager = DeviceManager(bus=bus, devices=[mock])
    app = create_app(bus=bus, manager=manager)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as ws:
            response = client.post("/debug/simulate", json={"kind": "scanner", "value": "8712345"})
            assert response.status_code == 202
            message = ws.receive_json()

    assert message["type"] == "scanner.read"
    assert message["data"]["code"] == "8712345"


def test_simulate_returns_409_when_no_mock_device_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cfg, "debug", True)
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])
    app = create_app(bus=bus, manager=manager)

    with TestClient(app) as client:
        response = client.post("/debug/simulate", json={"kind": "rfid", "value": "x"})

    assert response.status_code == 409


def test_debug_router_not_mounted_when_debug_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg, "debug", False)
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])
    app = create_app(bus=bus, manager=manager)

    with TestClient(app) as client:
        response = client.post("/debug/simulate", json={"kind": "rfid", "value": "x"})

    assert response.status_code == 404
