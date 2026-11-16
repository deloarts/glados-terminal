"""
src/api/app.py

FastAPI app factory. Wires the event bus and device manager (built by the
composition root, src/main.py) into FastAPI's lifespan, and the device
identity store into GET /identity and POST /identity/sign, and the
display controller and device reader (src/host/) into GET /display,
POST /display and GET /device. No business
logic and no auth checks here -- see CLAUDE.md's hard rules; this process is device I/O and
credential storage only, bound to 127.0.0.1 (or 0.0.0.0 inside the
bridge container, where the loopback guarantee is enforced by the Docker
Compose port mapping instead, see docker-compose.yml).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.debug import router as debug_router
from src.api.endpoints import router as endpoints_router
from src.api.host import router as host_router
from src.api.identity import router as identity_router
from src.api.websocket import router as websocket_router
from src.const import VERSION
from src.devices.manager import DeviceManager
from src.events.bus import EventBus
from src.host.device_info import DeviceInfoReader
from src.host.display import DisplayController
from src.identity.store import IdentityStore
from src.infrastructure.config import cfg
from src.infrastructure.logging.logger import log


def create_app(
    bus: EventBus,
    manager: DeviceManager,
    identity: IdentityStore | None = None,
    display: DisplayController | None = None,
    device_info: DeviceInfoReader | None = None,
) -> FastAPI:
    """`identity`, `display` and `device_info` are None when they are not
    wired, e.g. in tests that only exercise devices; their routes then
    answer 503."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await manager.start()
        log.info("Glados Terminal bridge started on %s:%d.", cfg.bridge.host, cfg.bridge.port)
        yield
        await manager.stop()
        log.info("Glados Terminal bridge shutting down.")

    app = FastAPI(title="Glados Terminal Bridge", version=VERSION, lifespan=lifespan)
    app.state.bus = bus
    app.state.manager = manager
    app.state.identity = identity
    app.state.display = display
    app.state.device_info = device_info

    # Browser origin allowlist for the status endpoints. WebSockets are
    # not subject to CORS at all, so /ws/events enforces the same list
    # itself (src/api/websocket.py). An empty list fails closed: no
    # browser origin gets a CORS header, and the warning below is the
    # only clue, so it is worth being loud about.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.bridge.allowed_origins,
        # Nothing here reads cookies or Authorization headers -- this
        # process has no auth to enforce -- so credentialed requests stay
        # off, which also keeps the wildcard-with-credentials footgun out
        # of reach.
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    if not cfg.bridge.allowed_origins:
        log.warning(
            "BRIDGE__ALLOWED_ORIGINS is empty: no browser may read /health or /devices, "
            "and /ws/events rejects every connection that sends an Origin header. Set it "
            "to the origin serving glados-frontend on this device."
        )

    app.include_router(endpoints_router)
    app.include_router(identity_router)
    app.include_router(host_router)
    app.include_router(websocket_router)

    if cfg.debug:
        app.include_router(debug_router)
        log.warning("DEBUG=true: /debug/simulate is mounted. Never enable this in production.")

    return app
