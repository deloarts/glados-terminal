---
name: architecture
description: Before changing code, understand where this code belongs in the bridge's layering and the WebSocket event schema. Load when adding a device type, touching the event bus, or wiring new API surface.
---

# Glados Terminal architecture

Glados Terminal is the shop-floor kiosk terminal: a Python 3.13 FastAPI hardware bridge daemon that
owns local devices (RFID reader, QR/barcode scanner, more later) and pushes their events to
whatever glados-frontend page is running in the kiosk's Chromium window, over a WebSocket. It also
keeps this device's identity (an Ed25519 key pair and the API key) for that page and signs its sign-in
challenge. It carries no business logic
and makes no authentication decisions — see CLAUDE.md's hard rules before adding either.

## Directory layout

```
src/
├── main.py                  # composition root: config, event bus, device manager, FastAPI app
├── infrastructure/
│   ├── config.py             # pydantic-settings: BRIDGE__*, per-device *__ENABLED/*__DEVICE_PATH
│   └── logging/logger.py     # single global `log`
├── events/
│   ├── bus.py                 # asyncio pub/sub: EventBus, Subscription (one bounded queue each)
│   └── types.py                # frozen dataclasses: RfidTagRead, ScannerRead, DeviceStatusChanged
├── devices/
│   ├── base.py                # Device ABC: name, status, async start()/stop()
│   ├── manager.py              # DeviceManager: lifecycle + supervision + backoff restart
│   ├── rfid_evdev.py            # evdev keyboard-wedge RFID reader (hardware group, guarded import)
│   ├── scanner_serial.py         # pyserial-asyncio line-reader scanner (hardware group, guarded import)
│   └── mock.py                    # MockDevice: fully working, drives POST /debug/simulate + tests
├── identity/
│   └── store.py               # IdentityStore: Ed25519 key pair (state dir), sign(), API key from env
├── host/
│   ├── device_info.py          # DeviceInfoReader: computer, host OS, display connectors for GET /device
│   ├── edid.py                  # parse_edid(): make, model, serial, native mode, size
│   ├── display.py               # DisplayController: power on/off through sway and CEC, display state
│   ├── sway.py                  # SwayClient: sway IPC over the kiosk's shared socket
│   ├── cec.py                   # CecClient: standby / image-view-on through cec-ctl
│   └── sysfs.py                 # tolerant readers for /proc and /sys
└── api/
    ├── app.py                   # FastAPI app factory, lifespan wiring
    ├── endpoints.py               # GET /health, GET /devices
    ├── identity.py                 # GET /identity (public key + API key), POST /identity/sign
    ├── host.py                     # GET /display, POST /display, GET /device
    ├── origins.py                  # origin_allowed(): server-side BRIDGE__ALLOWED_ORIGINS check
    ├── websocket.py                # GET /ws/events: fans out bus events as JSON
    └── debug.py                     # POST /debug/simulate (only mounted when DEBUG=true)
```

## Dependency direction (layering rule)

`api → events → devices`, one-directional:

- `src/devices/` may import `src/events/` (to publish events) and `src/infrastructure/`. It must
  **never** import anything from `src/api/`. A device is standalone I/O; it has no notion of HTTP,
  WebSockets, or FastAPI at all.
- `src/api/` may import `src/events/` (to subscribe/publish) and `src/devices/` (only
  `manager.py`/`mock.py`, to read device status and drive the debug endpoint — never a concrete
  hardware driver class directly).
- `src/events/` imports nothing from either `api` or `devices` — it's the shared vocabulary both
  sides depend on.
- `src/identity/` imports only `src/infrastructure/`; `src/api/` reads it for `GET /identity` and
  `POST /identity/sign`. It keeps the key, signs with it and never validates a credential.
- `src/host/` imports only `src/infrastructure/`; `src/api/` reads it for `GET /display`,
  `POST /display` and `GET /device`. It switches the display when asked and reads the device's
  facts, it never decides when a display is off.
- `src/infrastructure/` (config, logging) is cross-cutting and importable from anywhere.

**Red flag:** any `from src.api...` import inside `src/devices/` — stop and restructure, that
import points the wrong way.

## The event envelope

Every event is a frozen dataclass in `src/events/types.py` with a `to_envelope()` producing the one
wire schema sent over `GET /ws/events`:

```json
{"type": "rfid.tag_read" | "scanner.read" | "device.status",
 "device": "<device name>", "ts": "<UTC ISO 8601>", "data": {...}}
```

| Event                | `type`              | `data`                                    |
| --------------------- | -------------------- | ------------------------------------------ |
| `RfidTagRead`          | `rfid.tag_read`       | `{"tag": "<uid>"}`                          |
| `ScannerRead`           | `scanner.read`         | `{"code": "<payload>", "symbology": ...}`    |
| `DeviceStatusChanged`    | `device.status`         | `{"status": "starting"\|"ready"\|"error"\|"stopped", "detail": ...}` |

`ts` is always `datetime.now(UTC)` at construction (family-wide UTC/timezone-aware rule) — never a
naive datetime, never anything but the ISO 8601 form on the wire.

## Recipe: adding a new device type

1. Add a settings model to `src/infrastructure/config.py` (e.g. `FooDeviceSettings` with at least
   `enabled: bool = False`) and wire it onto `Settings`.
2. Add whatever event type(s) it needs to `src/events/types.py` (a frozen dataclass with a
   `to_envelope()`), and add it to the `BridgeEvent` union.
3. Create `src/devices/foo_something.py`: subclass `Device` (`src/devices/base.py`), implement
   `start()` (open the device, publish `DeviceStatusChanged(..., status="ready")` once actually
   open, then loop forever publishing events until cancelled or the device errors) and `stop()`
   (release the device handle, idempotent). If it needs a third-party driver library, guard the
   import the way `rfid_evdev.py`/`scanner_serial.py` do (module-level `try: import x / except
   ImportError: x = None`, plus an `if x is None: raise ImportError(...)` in `__init__`) and add
   the dependency to the `hardware` Poetry group in `pyproject.toml`, not the main group.
4. Wire it into `_build_devices()` in `src/main.py`, gated on its `*.enabled` config flag, matching
   the existing `rfid`/`scanner` entries.
5. Add its env vars to `.env.example`, `.env.dev.example`, and the tables in
   `docs/DEVELOPMENT.md`/`docs/INSTALLATION.md`.
6. Add tests: a unit test for the new event type's `to_envelope()` shape if it's non-trivial, and a
   `DeviceManager` lifecycle test the way `tests/test_mock_device_manager.py` covers `MockDevice`
   (a fake/mock version of the new device, not real hardware, is what the test suite drives).

## Config/env conventions

`pydantic-settings` with a nested `SECTION__FIELD` pattern and an `ENV_FILE` mechanism: each config section is a `BaseModel`, composed onto one `Settings(BaseSettings)`
with `env_nested_delimiter="__"`. `ENV_FILE=.env.dev poetry run uvicorn src.main:app --reload` for
local dev; plain `.env` under Docker Compose. `BRIDGE__HOST` defaults to `127.0.0.1` — see
CLAUDE.md's hard rule before ever changing that default.
