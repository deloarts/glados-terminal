# developing

- [developing](#developing)
  - [1 prerequisites](#1-prerequisites)
  - [2 install dependencies](#2-install-dependencies)
  - [3 configure the environment](#3-configure-the-environment)
  - [4 run the bridge](#4-run-the-bridge)
  - [5 exercise it without hardware](#5-exercise-it-without-hardware)
  - [6 build and run the containers locally](#6-build-and-run-the-containers-locally)
  - [7 quality gates](#7-quality-gates)
  - [8 datetime convention](#8-datetime-convention)
  - [9 test conventions](#9-test-conventions)

## 1 prerequisites

- Python 3.13 (the project targets 3.13 exactly, matching the Docker base image)
- [Poetry](https://python-poetry.org/) for dependency management
- Docker, plus the Compose plugin — only needed for [section 6](#6-build-and-run-the-containers-locally); the day-to-day dev loop below is Poetry-native, no containers required.

> [!NOTE]
> There is no real hardware on a dev machine (usually). The mock device
> (`src/devices/mock.py`) plus `POST /debug/simulate` cover frontend
> development and the test suite end to end — see
> [section 5](#5-exercise-it-without-hardware).

## 2 install dependencies

```bash
poetry install
```

This installs the main + dev groups only. `evdev` and `pyserial-asyncio` (the actual hardware
drivers) live in an **optional** `hardware` group and are not needed to run tests, lint, or the
mock device:

```bash
poetry install --with hardware
```

Only do this on a Linux machine where you actually want to import `src/devices/rfid_evdev.py` or
`src/devices/scanner_serial.py` directly (e.g. testing against a real reader plugged into a dev
machine). Both modules guard their own import and raise a clear error only if that device type is
enabled in config — see the `architecture` skill.

Install the git hooks (gitleaks, ruff, mypy, import-linter and the planning-label check on commit,
see `.pre-commit-config.yaml`):

```bash
poetry run pre-commit install
```

## 3 configure the environment

Local development is configured via `.env.dev` (`cp .env.dev.example .env.dev` to create it — the
template already enables the mock device). All settings are read by `src/infrastructure/config.py`
(a `pydantic-settings` model, same `__` nesting delimiter and `ENV_FILE` mechanism as
the Glados backend):

| Group    | Env vars                                                              | Maps to                 |
| -------- | ---------------------------------------------------------------------- | ------------------------ |
| App      | `DEBUG`, `LOG_LEVEL`, `LOG_FORMAT`                                     | `Settings`               |
| Bridge   | `BRIDGE__HOST`, `BRIDGE__PORT`                                          | `BridgeSettings`         |
| RFID     | `RFID__ENABLED`, `RFID__DEVICE_PATH`                                    | `RfidDeviceSettings`     |
| Scanner  | `SCANNER__ENABLED`, `SCANNER__DEVICE_PATH`, `SCANNER__BAUD_RATE`        | `ScannerDeviceSettings`  |
| Mock     | `MOCK__ENABLED`                                                         | `MockDeviceSettings`     |
| Identity | `IDENTITY__STATE_DIR`, `IDENTITY__API_KEY`                              | `IdentitySettings`       |
| System   | `SYSTEM__OS_RELEASE_PATH`, `SYSTEM__HOSTNAME_PATH`, `SYSTEM__SWAY_SOCKET_DIR` | `SystemSettings` |

Point `pydantic-settings` at the file via `ENV_FILE`:

```bash
ENV_FILE=.env.dev poetry run uvicorn src.main:app --reload --port 8600
```

> [!IMPORTANT]
> `BRIDGE__HOST` defaults to `127.0.0.1` and `.env.dev.example` does not override it. Never set it
> to `0.0.0.0` for a bare Poetry/uvicorn run — that is only done inside the Docker Compose setup
> (`docker-compose.yml`), where the loopback guarantee moves to the compose port mapping instead.
> See CLAUDE.md's hard rules.

## 4 run the bridge

```bash
ENV_FILE=.env.dev poetry run uvicorn src.main:app --reload --port 8600
```

## 5 exercise it without hardware

With `MOCK__ENABLED=true` (the `.env.dev.example` default) and `DEBUG=true`, `POST /debug/simulate`
is mounted:

```bash
curl http://127.0.0.1:8600/health
curl http://127.0.0.1:8600/devices
curl -X POST http://127.0.0.1:8600/debug/simulate \
  -H "content-type: application/json" \
  -d '{"kind": "rfid", "value": "0123456789"}'
```

A client connected to `ws://127.0.0.1:8600/ws/events` (e.g. `websocat`, a browser devtools console,
or the frontend dev server) receives the event as soon as it's simulated:

```json
{"type": "rfid.tag_read", "device": "mock", "ts": "2026-01-01T12:00:00+00:00", "data": {"tag": "0123456789"}}
```

The full envelope schema (all three event types) is documented in the `architecture` skill and the
README.

The device identity the kiosk page signs in with is an Ed25519 key pair. With `.env.dev.example`'s
`IDENTITY__STATE_DIR=.state`, the first request to either identity route creates
`.state/device_key.pem`; delete the directory to get a fresh identity.

```bash
curl http://127.0.0.1:8600/identity
curl -X POST http://127.0.0.1:8600/identity/sign \
  -H "content-type: application/json" \
  -d '{"nonce": "0123456789abcdefghijklmnopqrstuvwxyz"}'
```

`GET /identity` answers `{"public_key": ..., "api_key": ...}`, where `public_key` is the raw 32-byte
key in base64url without padding and `api_key` is `IDENTITY__API_KEY` or `null`. `POST /identity/sign`
answers `{"signature": ...}`, the 64-byte Ed25519 signature over `glados-terminal-auth-v1:` followed
by the nonce, also base64url without padding. The nonce must use the base64url alphabet plus `.` and be 32
to 128 characters long, otherwise the answer is a 422. See CLAUDE.md's Bridge protocol section for the
403 and 503 cases.

`GET /device` and `GET /display` work on a dev machine too. The `SYSTEM__*` defaults point at the
paths `docker-compose.yml` mounts, so on a bare run the host fields of `GET /device` are `null` and
`sway_reachable` is `false`; set `SYSTEM__OS_RELEASE_PATH=/etc/os-release` and
`SYSTEM__HOSTNAME_PATH=/etc/hostname` in `.env.dev` to see your own machine. `POST /display` answers
503 without a sway socket in `SYSTEM__SWAY_SOCKET_DIR`; under a sway session of your own, pointing it
at `$XDG_RUNTIME_DIR` switches your own screens. Every route's JSON is in
[BRIDGE_API.md](BRIDGE_API.md).

```bash
curl http://127.0.0.1:8600/device
curl http://127.0.0.1:8600/display
```

## 6 build and run the containers locally

Only needed to test the actual deployment shape (`docker-compose.yml`) before pushing —
day-to-day development stays Poetry-native (sections 1–5). `docker-compose.yml` itself only pulls
the published `linux/arm64` images; `docker-compose.build.yml` adds the `build:` sections, so the
images are built from this checkout for the dev machine's own architecture:

```bash
cp .env.example .env   # fill in KIOSK_URL at minimum
docker compose -f docker-compose.yml -f docker-compose.build.yml build
docker compose up -d
docker compose logs -f bridge
```

The local build gets the image names the device would pull, so the plain `docker compose up -d`
afterwards runs it. Run `docker compose pull` to go back to the published images.

> [!NOTE]
> The `bridge` image's builder stage compiles `evdev`/`pyserial-asyncio` (the `hardware` Poetry
> group) from source on architectures without prebuilt wheels — expect the first build to take
> noticeably longer than the bare Poetry install in section 2.

The `kiosk` container needs a real DRM/KMS display (`/dev/dri`) and will not come up usefully on a
plain dev laptop with a desktop session already running — see
[docs/INSTALLATION.md](INSTALLATION.md) for the target device setup. `bridge` alone runs fine
anywhere Docker does.

## 7 quality gates

What CI's `verify`, `plan-refs` and `gitleaks` jobs check, runnable locally (most of it also runs
as pre-commit hooks):

```bash
poetry run ruff format src tests scripts
poetry run ruff check src tests scripts
poetry run mypy src
poetry run lint-imports
poetry run pytest tests -q --cov=src
python3 scripts/check_plan_refs.py
```

`lint-imports` enforces the layering from CLAUDE.md (contracts in `pyproject.toml`), and the
pytest run fails below the coverage floor (`fail_under` in `pyproject.toml`). Versioning, the
release flow and the full CI job list are in [RELEASING.md](RELEASING.md).

## 8 datetime convention

Store every datetime as UTC and timezone-aware (`datetime.now(UTC)`, never naive) — the family-wide
rule, also enforced by the WebSocket event envelope's `ts` field (`src/events/types.py`), which is
always an ISO 8601 string with a UTC offset.

## 9 test conventions

Plain `pytest`, run with `-q`, flat `tests/` directory (no `unit`/`integration` split — this repo
has no database or external services to separate against). `asyncio_mode = "auto"` in
`pyproject.toml` means an `async def test_...` function needs no `@pytest.mark.asyncio` decorator.
Tests that depend on a background device task reaching a status (e.g. the mock device becoming
"ready") poll briefly with a bounded timeout rather than sleeping a fixed duration — see
`tests/test_mock_device_manager.py` and `tests/test_health_and_devices.py` for the pattern.
