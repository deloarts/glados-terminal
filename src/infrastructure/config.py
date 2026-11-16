"""
src/infrastructure/config.py

pydantic-settings configuration for the hardware bridge daemon, with a
nested `SECTION__FIELD` env-var pattern and an ENV_FILE mechanism:
each section is a BaseModel, composed into one Settings(BaseSettings) with
`env_nested_delimiter="__"`. ENV_FILE picks the file to load at import
time -- `ENV_FILE=.env.dev poetry run uvicorn src.main:app --reload` for
local dev (see docs/DEVELOPMENT.md), plain `.env` under Docker Compose
(see docker-compose.yml).

BRIDGE__HOST defaults to 127.0.0.1: the bridge must never be reachable
from the network, this is a hard project rule (see CLAUDE.md). Inside the
Docker Compose setup the bridge process itself binds 0.0.0.0 (compose
sets BRIDGE__HOST via `environment:`) so the container's own network
stack can be reached at all -- the loopback-only guarantee then moves to
the compose port mapping ("127.0.0.1:8600:8600") instead of the bind
address. See docker-compose.yml and docs/INSTALLATION.md.

BRIDGE__ALLOWED_ORIGINS is the browser-facing counterpart to that rule:
binding to loopback keeps other *hosts* out, the origin allowlist keeps
other *pages* out (see BridgeSettings.allowed_origins).
"""

import os
from typing import Annotated
from typing import Literal

from pydantic import BaseModel
from pydantic import field_validator
from pydantic_settings import BaseSettings
from pydantic_settings import NoDecode
from pydantic_settings import SettingsConfigDict


class BridgeSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8600
    # Browser origins allowed to talk to this bridge, i.e. wherever the
    # glados-frontend page this device displays is served from. This
    # process has no authentication of its own (CLAUDE.md), so the origin
    # allowlist is all that separates the device event stream from any
    # other page the kiosk's Chromium happens to load. Defaults to empty,
    # which fails closed and logs a warning on startup (src/api/app.py).
    #
    # Comma-separated, NOT a JSON array: `NoDecode` opts this field out of
    # pydantic-settings' JSON decoding for complex types, so a plain
    # `BRIDGE__ALLOWED_ORIGINS=https://a.example.com,http://localhost:5173`
    # works in a .env file.
    allowed_origins: Annotated[list[str], NoDecode] = []

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


class RfidDeviceSettings(BaseModel):
    enabled: bool = False
    # /dev/input/by-id/... path -- stable across reboots/re-plugging,
    # unlike /dev/input/eventN (see docs/INSTALLATION.md).
    device_path: str = "/dev/input/by-id/change_me-rfid-reader"


class ScannerDeviceSettings(BaseModel):
    enabled: bool = False
    # /dev/serial/by-id/... path -- stable across reboots, unlike
    # /dev/ttyUSBn (see docs/INSTALLATION.md).
    device_path: str = "/dev/serial/by-id/change_me-scanner"
    baud_rate: int = 9600


class MockDeviceSettings(BaseModel):
    enabled: bool = False


class IdentitySettings(BaseModel):
    # Where the generated device key pair lives (device_key.pem). Under
    # Docker Compose this is a named volume (docker-compose.yml), so the
    # key survives image rebuilds; removing the volume gives the device a
    # new identity.
    state_dir: str = "/var/lib/glados-terminal"
    # The terminal key created in Glados under Settings, API keys, "Create
    # terminal key". Handed to the kiosk page as is; the bridge never
    # checks it. Empty means none, which is right for a plain RFID or
    # scanner terminal.
    api_key: str = ""


class SystemSettings(BaseModel):
    # The host's /etc/os-release and /etc/hostname, mounted read-only into
    # the bridge container by docker-compose.yml. The container's own
    # copies describe the bridge image, not the device, so they are never
    # read instead; GET /device reports the fields as null when these are
    # missing, e.g. in a bare Poetry run.
    os_release_path: str = "/host/etc/os-release"
    hostname_path: str = "/host/etc/hostname"
    # The kiosk container's runtime directory, where sway keeps its IPC
    # socket, shared into the bridge container by the `kiosk-runtime`
    # volume in docker-compose.yml. POST /display switches the display
    # through that socket.
    sway_socket_dir: str = "/run/kiosk"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    debug: bool = False
    app_name: str = "Glados Terminal Bridge"
    # Throttles the StreamHandler only, see logging/logger.py.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "DEBUG"
    # Stdout line format: "text" for humans, "json" for a log aggregator.
    log_format: Literal["text", "json"] = "text"

    bridge: BridgeSettings = BridgeSettings()
    rfid: RfidDeviceSettings = RfidDeviceSettings()
    scanner: ScannerDeviceSettings = ScannerDeviceSettings()
    mock: MockDeviceSettings = MockDeviceSettings()
    identity: IdentitySettings = IdentitySettings()
    system: SystemSettings = SystemSettings()


cfg = Settings()
