"""
tests/test_origin_allowlist.py

Coverage for the browser origin allowlist (BRIDGE__ALLOWED_ORIGINS):
CORS headers on the status endpoints (src/api/app.py) and the Origin
check on GET /ws/events (src/api/websocket.py).

`cfg` is a module-level singleton, and the two consumers read it at
different times -- CORSMiddleware at create_app(), the websocket check per
connection -- so every test patches cfg.bridge.allowed_origins BEFORE
building the app, which is correct for both.
"""

import pytest
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocketDisconnect

from src.api.app import create_app
from src.devices.manager import DeviceManager
from src.events.bus import EventBus
from src.infrastructure.config import cfg

ALLOWED = "https://glados.example.com"
DISALLOWED = "https://evil.example.com"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(cfg.bridge, "allowed_origins", [ALLOWED])
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])
    return TestClient(create_app(bus=bus, manager=manager))


def test_allowed_origin_gets_a_cors_header(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": ALLOWED})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_disallowed_origin_gets_no_cors_header(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": DISALLOWED})

    # The request itself still succeeds -- CORS is enforced by the browser
    # refusing to hand the body to JS, not by the server refusing to serve.
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_websocket_accepts_an_allowed_origin(client: TestClient) -> None:
    with client:
        with client.websocket_connect("/ws/events", headers={"Origin": ALLOWED}) as ws:
            assert ws is not None


def test_websocket_rejects_a_disallowed_origin(client: TestClient) -> None:
    with client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/events", headers={"Origin": DISALLOWED}):
                pass


def test_websocket_allows_a_missing_origin(client: TestClient) -> None:
    # Non-browser clients (curl, this suite, the smoke script) send no
    # Origin at all, and must keep working -- see _origin_allowed's docstring.
    with client:
        with client.websocket_connect("/ws/events") as ws:
            assert ws is not None


def test_empty_allowlist_rejects_every_browser_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.bridge, "allowed_origins", [])
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])
    empty_client = TestClient(create_app(bus=bus, manager=manager))

    with empty_client:
        with pytest.raises(WebSocketDisconnect):
            with empty_client.websocket_connect("/ws/events", headers={"Origin": ALLOWED}):
                pass
