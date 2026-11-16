"""
tests/test_websocket.py

Coverage for GET /ws/events (src/api/websocket.py): a connected client
receives an event published on the bus, encoded per the documented
envelope schema. Publishing runs through `client.portal` (Starlette
TestClient's blocking portal into the app's own event loop) rather than
calling bus.publish() straight from the test thread -- asyncio.Queue is
not thread-safe, and the app's event loop runs on TestClient's own
thread once inside the `with` block.
"""

from fastapi.testclient import TestClient

from src.api.app import create_app
from src.devices.manager import DeviceManager
from src.events.bus import EventBus
from src.events.types import RfidTagRead


def test_websocket_receives_published_event() -> None:
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])
    app = create_app(bus=bus, manager=manager)
    event = RfidTagRead(device="rfid", tag="abc123")

    async def _publish() -> None:
        bus.publish(event)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as ws:
            client.portal.call(_publish)
            message = ws.receive_json()

    assert message == {
        "type": "rfid.tag_read",
        "device": "rfid",
        "ts": event.ts.isoformat(),
        "data": {"tag": "abc123"},
    }


def test_multiple_connected_clients_each_receive_the_event() -> None:
    bus = EventBus()
    manager = DeviceManager(bus=bus, devices=[])
    app = create_app(bus=bus, manager=manager)
    event = RfidTagRead(device="rfid", tag="xyz789")

    async def _publish() -> None:
        bus.publish(event)

    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as ws_a:
            with client.websocket_connect("/ws/events") as ws_b:
                client.portal.call(_publish)
                message_a = ws_a.receive_json()
                message_b = ws_b.receive_json()

    assert message_a["data"] == {"tag": "xyz789"}
    assert message_b["data"] == {"tag": "xyz789"}
