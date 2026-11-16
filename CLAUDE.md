# Glados Terminal

## Project overview

Glados is a manufacturing / production-planning system: catalogue items, demands, procurement,
production lots, scheduling, QA. This repo is the shop-floor kiosk terminal: a Python 3.13 FastAPI
**hardware bridge daemon** running on a Raspberry Pi (DietPi) at the machine/workstation.

This repo does **not** host, build, or render glados-frontend. It owns local devices (RFID reader,
QR/barcode scanner, more later) and pushes their events to whatever glados-frontend page is running
in the kiosk's Chromium window, over a WebSocket. It also keeps this device's identity (a generated
Ed25519 key pair plus the API key from `.env`): it hands the public key and the API key to that page
and signs the sign-in challenge the page gets from glados-backend. The private key never leaves the
bridge. It carries no business logic and makes no authentication decisions —
those live in glados-backend; the frontend consumes bridge events and talks to the backend directly
for everything else.

## Architecture

- Layering is `api → events → devices`, one-directional: `src/api/` may import `src/events/`,
  `src/devices/`, `src/identity/` and `src/host/`; `src/identity/` and `src/host/` import only `src/infrastructure/`; `src/devices/` may import `src/events/`; `src/devices/` never imports anything
  from `src/api/`. `src/infrastructure/` (config, logging) is cross-cutting, imported from
  anywhere.
- Composition root `src/main.py` builds the config, the event bus, and the device manager (wiring
  in whichever devices are enabled), then hands them to `src/api/app.py`'s `create_app()`, which
  wires them into FastAPI's lifespan. Devices publish events onto a shared in-process `EventBus`
  (`src/events/bus.py`); `GET /ws/events` fans them out to every connected WebSocket client.
- `DeviceManager` (`src/devices/manager.py`) supervises each device's read loop as its own
  background task and restarts a crashed one with exponential backoff — a device failure degrades
  that one device's reported status, it never takes the daemon down.
- See the `architecture` skill for the directory layout and the recipe for adding a new device
  type.

## Bridge protocol / boundary

- The bridge binds `127.0.0.1` only — a hard rule, see Don't below. Under the Docker Compose setup
  (`docker-compose.yml`) the bridge process binds `0.0.0.0` *inside* its container so the container
  can be reached at all; the loopback guarantee then comes from the compose port mapping
  (`"127.0.0.1:8600:8600"`) instead of the bind address. The `kiosk` container shares the bridge
  container's network namespace (`network_mode: "service:bridge"`) specifically so that
  `ws://localhost:8600` inside Chromium resolves to the bridge — Chromium exempts `localhost` from
  mixed-content blocking, which is what lets an HTTPS-origin glados-frontend page talk to a plain
  `ws://` bridge at all.
- Every event on the bus is a frozen dataclass (`src/events/types.py`: `RfidTagRead`,
  `ScannerRead`, `DeviceStatusChanged`) with a `to_envelope()` matching the one wire schema sent
  over `GET /ws/events`:

  ```json
  {"type": "rfid.tag_read" | "scanner.read" | "device.status",
   "device": "<device name>", "ts": "<UTC ISO 8601>", "data": {...}}
  ```

- `GET /health` and `GET /devices` are read-only status endpoints (no auth — this process has none
  to enforce).
- The device identity (`src/identity/store.py`, `src/api/identity.py`) is an Ed25519 key pair
  generated once into `IDENTITY__STATE_DIR` (`device_key.pem`, PKCS8 PEM, mode 0600, a named Docker
  volume) and kept across image rebuilds. An invalid key file is an error for a human (delete it),
  never silently replaced.
- `GET /identity` returns `{"public_key": "<raw 32-byte key, base64url, no padding>", "api_key":
  "<IDENTITY__API_KEY>" | null}`.
- `POST /identity/sign` takes `{"nonce": "<base64url alphabet or dots, 32 to 128 chars>"}` and returns
  `{"signature": "<64-byte Ed25519 signature, base64url, no padding>"}` over the bytes
  `b"glados-terminal-auth-v1:" + nonce`. Any other nonce gets a 422; the bridge checks nothing else.
- Both identity routes: a present `Origin` outside `BRIDGE__ALLOWED_ORIGINS` gets a 403 (checked
  before the body), not just a missing CORS header; a missing `Origin` is allowed; a missing store
  or an unusable state directory or key file gets a 503, never a crash; responses carry
  `Cache-Control: no-store`.
- `GET /display` and `POST /display` (`{"power": "on" | "off"}`) report and switch the display:
  sway over its IPC socket in the shared `kiosk-runtime` volume (`src/host/sway.py`, `power` or
  `dpms` by sway version) and HDMI-CEC through `cec-ctl` (`src/host/cec.py`). `GET /device`
  reports the computer, host OS, display connectors with parsed EDID, and the display state
  (`src/host/device_info.py`). All three are origin-checked like the identity routes, answer
  `Cache-Control: no-store`, and 503 when not wired or when sway cannot switch. Every route's
  exact JSON is in `docs/BRIDGE_API.md`; keep it in step with any change.
- `POST /debug/simulate` is only mounted when `DEBUG=true` and only works if a `MockDevice` is
  configured (`MOCK__ENABLED=true`) — it injects a simulated `rfid`/`scanner` event for frontend
  development without hardware attached.
- The frontend must keep working with the bridge absent or degraded: a missing/errored device shows
  up as a `device.status` event and an entry in `GET /devices` with `status: "error"`, never as a
  crashed bridge or a broken page.

## Commands

- `poetry install` (main + dev groups); `poetry install --with hardware` only when actually testing
  against real evdev/serial hardware — see the `architecture` skill and `docs/DEVELOPMENT.md`.
- Hooks: `poetry run pre-commit install`.
- Tests: `poetry run pytest tests -q`; targeted: `poetry run pytest tests/test_x.py -q`.
- Gates: `poetry run ruff check src tests scripts`, `poetry run ruff format --check src tests
  scripts`, `poetry run mypy src` (strict), `poetry run lint-imports` (the layering above),
  `python3 scripts/check_plan_refs.py`; pytest with `--cov=src` enforces the coverage floor.
- Dev server: `ENV_FILE=.env.dev poetry run uvicorn src.main:app --reload --port 8600`.
- Containers (only to test the deployment shape locally, see `docs/DEVELOPMENT.md` section 6):
  `docker compose -f docker-compose.yml -f docker-compose.build.yml build`, `docker compose up -d`.
  `docker-compose.yml` itself has no `build:`; devices pull the arm64 images from GHCR.
- Release: `scripts/release_start.sh X.Y.Z` (see `docs/RELEASING.md`); version bumps only via
  `scripts/bump_version.sh X.Y.Z`, which also moves `docker-compose.yml`'s default image tag.

## Coding conventions

- Single global logger `from src.infrastructure.logging.logger import log` (no request contextvars
  — this process has no request/user identity worth stamping, just device I/O). Every module opens
  with a docstring explaining its purpose and any non-obvious decisions; inline comments stay
  sparse.
- Datetimes: UTC, timezone-aware, always (family rule) — `datetime.now(UTC)`, never naive. The
  event envelope's `ts` is always its ISO 8601 form.
- Events are frozen dataclasses (`src/events/types.py`), never mutated after creation.
- `rfid_evdev.py` and `scanner_serial.py` guard their hardware imports (`try: import evdev / except
  ImportError: evdev = None`) so a plain `poetry install` (no `hardware` group) still works; the
  `ImportError` is only raised from `__init__`, i.e. only if that device type is actually enabled
  in config.

## Don't

1. Never bind the bridge to a non-localhost interface. `BRIDGE__HOST` stays `127.0.0.1` outside of
   `docker-compose.yml`'s `environment:` override, and that override only exists because the
   compose port mapping (`"127.0.0.1:8600:8600"`) is what actually enforces loopback-only access —
   never remove that prefix or add another published port for this service.
2. Never add business logic or authentication decisions to the bridge. It reports device I/O,
   stores this device's credentials and signs with its key, but it never checks a credential or decides anything from one;
   every decision (who's allowed to badge in, what a scanned code means, whether this device is
   approved and what it shows) belongs in glados-backend or glados-frontend.
3. Never let a device failure crash the daemon. A device driver's job is to raise into
   `DeviceManager`'s supervision loop (or simply stop, which is treated the same way) so it can be
   restarted with backoff and reported as `"error"` — not to take the FastAPI process down.
4. The frontend must keep working when the bridge is absent — never build a bridge feature that the
   frontend cannot gracefully do without (see the Bridge protocol section above).
5. Never add a "Co-Authored-By: Claude" (or any AI) trailer to commit messages, and never commit or
   push unprompted; wait for an explicit ask every time.
6. Never change an existing test to make new code pass without flagging it first.
7. Never reference plan-points or decision-points (e.g. `D13`, `WP-A4`) or `.playground/` in code
   comments or documentation — plans are local working artifacts; code and docs must stand alone.
8. Always write German user-facing copy (should any ever appear on this bridge's own responses) in
   informal "Du", never "Sie" — this bridge has no UI of its own today, but the rule is family-wide.

## Workflow

- Trunk-based: `main` is the only long-lived branch; every change is a squash-merged PR from a
  `feat/*` or `fix/*` branch cut from `main`. A release is a PR from `release/X.Y.Z`; merging it
  tags and publishes (`docs/RELEASING.md`). Versions are `0.Y.Z`, the first release is
  `0.1.0`; a bridge protocol change is a minor.
- `.playground/` (gitignored) is the planning and decision-record hub: one folder per effort,
  `<topic>-<YYYY-MM-DD>/plan.md` with Goal, pinned Decisions (Dxx), Confirmations, Findings,
  Target behaviour, Implementation breakdown, Traceability.
- Pinned decisions (Dxx) in a plan are settled — do not relitigate them without a new, explicit
  reason from the user.

## Docs

- `docs/DEVELOPMENT.md` — local setup, the `ENV_FILE` pattern, running without hardware (mock
  device + `/debug/simulate`), release checks.
- `docs/INSTALLATION.md` — provisioning a DietPi kiosk device: Docker install, `docker-compose.yml`
  pull/start (directly or as a Portainer stack, central with the Edge Agent or per device), finding `by-id` device paths for the RFID reader and scanner, infoscreen setup
  (terminal key, pairing), hardening the device, upgrade/uninstall.
- `docs/BRIDGE_API.md`: every HTTP and WebSocket route with its exact JSON, the contract
  glados-frontend codes against.
- `docs/RELEASING.md` — versioning policy, the trunk-based release flow, what each CI job checks,
  the release-candidate channel, the GitHub settings it relies on. `CHANGELOG.md` gets a line under
  `[Unreleased]` for every change an operator should know about.
