"""
src/api/websocket.py

GET /ws/events: the frontend's only way to receive device events. Each
connection subscribes to the shared EventBus (src/events/bus.py) and
forwards every event as JSON, matching the envelope documented in the
`architecture` skill and README. One client's slow socket write can't
affect another's -- isolation happens one layer down, in the bus's
per-subscriber queue, not here.

WebSockets are exempt from the same-origin policy and from CORS, so the
CORS middleware in src/api/app.py does nothing for this route -- the
Origin check below (src/api/origins.py) is what keeps an unrelated page
loaded in the kiosk's Chromium from subscribing to the device stream
(which carries RFID tag IDs) on its own.
"""

from typing import cast

from fastapi import APIRouter
from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from starlette.websockets import WebSocketState

from src.api.origins import origin_allowed
from src.events.bus import EventBus
from src.infrastructure.logging.logger import log

router = APIRouter()


def _get_bus(websocket: WebSocket) -> EventBus:
    return cast(EventBus, websocket.app.state.bus)


@router.websocket("/ws/events")
async def events(websocket: WebSocket) -> None:
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin):
        # Closing before accept() answers the handshake with an HTTP
        # rejection, so the page never gets an open socket at all.
        log.warning("Rejected /ws/events connection from disallowed origin %r.", origin)
        await websocket.close(code=1008)
        return

    bus = _get_bus(websocket)
    await websocket.accept()
    subscription = bus.subscribe()
    try:
        while True:
            event = await subscription.get()
            await websocket.send_json(event.to_envelope())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(subscription)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
