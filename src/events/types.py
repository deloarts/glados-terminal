"""
src/events/types.py

Event envelope pushed onto the bus (src/events/bus.py) by device drivers
and fanned out to WebSocket clients (src/api/websocket.py). Every event's
`to_envelope()` matches the documented wire schema (see the
`architecture` skill and README):

    {"type": "rfid.tag_read" | "scanner.read" | "device.status",
     "device": "<device name>", "ts": "<UTC ISO 8601>", "data": {...}}

Frozen dataclasses only -- events are immutable facts a device observed,
never mutated after creation. `BridgeEvent` is the union every producer
(devices) and consumer (the bus, the websocket, tests) is typed against.
"""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class RfidTagRead:
    """An RFID badge/tag was read (src/devices/rfid_evdev.py, or
    simulated via src/devices/mock.py)."""

    device: str
    tag: str
    ts: datetime = field(default_factory=_utc_now)
    type: Literal["rfid.tag_read"] = "rfid.tag_read"

    def to_envelope(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "device": self.device,
            "ts": self.ts.isoformat(),
            "data": {"tag": self.tag},
        }


@dataclass(frozen=True, kw_only=True)
class ScannerRead:
    """A QR/barcode was scanned (src/devices/scanner_serial.py, or
    simulated via src/devices/mock.py)."""

    device: str
    code: str
    symbology: str | None = None
    ts: datetime = field(default_factory=_utc_now)
    type: Literal["scanner.read"] = "scanner.read"

    def to_envelope(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "device": self.device,
            "ts": self.ts.isoformat(),
            "data": {"code": self.code, "symbology": self.symbology},
        }


DeviceStatus = Literal["starting", "ready", "error", "stopped"]


@dataclass(frozen=True, kw_only=True)
class DeviceStatusChanged:
    """A device's status changed (src/devices/manager.py supervision loop,
    or a device announcing it reached "ready" itself)."""

    device: str
    status: DeviceStatus
    detail: str | None = None
    ts: datetime = field(default_factory=_utc_now)
    type: Literal["device.status"] = "device.status"

    def to_envelope(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "device": self.device,
            "ts": self.ts.isoformat(),
            "data": {"status": self.status, "detail": self.detail},
        }


BridgeEvent = RfidTagRead | ScannerRead | DeviceStatusChanged
