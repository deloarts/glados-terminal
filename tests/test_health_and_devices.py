"""
tests/test_health_and_devices.py

Coverage for GET /health and GET /devices (src/api/endpoints.py). The
mock device's start() reports "ready" from its own background task, so
these tests poll briefly for that instead of asserting on a fixed sleep.
"""

import time

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.devices.manager import DeviceManager
from src.devices.mock import MockDevice
from src.events.bus import EventBus


def _build_client() -> TestClient:
    bus = EventBus()
    mock = MockDevice(bus=bus, name="mock")
    manager = DeviceManager(bus=bus, devices=[mock])
    app = create_app(bus=bus, manager=manager)
    return TestClient(app)


def _wait_for_ready_devices(client: TestClient, timeout: float = 2.0) -> list[dict[str, str]]:
    deadline = time.monotonic() + timeout
    body: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        body = client.get("/devices").json()
        if body and all(d["status"] == "ready" for d in body):
            return body
        time.sleep(0.01)
    raise AssertionError(f"device(s) never became ready, last seen: {body}")


def test_health_reports_version_and_device_statuses() -> None:
    with _build_client() as client:
        _wait_for_ready_devices(client)
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["version"], str) and body["version"]
    assert body["devices"] == [{"name": "mock", "status": "ready"}]


def test_devices_lists_configured_devices() -> None:
    with _build_client() as client:
        devices = _wait_for_ready_devices(client)

    assert devices == [{"name": "mock", "status": "ready"}]


def test_devices_is_empty_when_none_configured() -> None:
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])
    app = create_app(bus=bus, manager=manager)

    with TestClient(app) as client:
        response = client.get("/devices")

    assert response.status_code == 200
    assert response.json() == []
