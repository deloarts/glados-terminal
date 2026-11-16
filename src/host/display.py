"""
src/host/display.py

Switches the display off and on when the glados-frontend page asks for
it (POST /display), and reports its state (GET /display). Glados decides
when a display is off; this only carries it out, the same way the
identity store only signs.

Off cuts the HDMI signal through sway and, when the display answers on
HDMI-CEC, also puts it into standby, because many TVs stay on showing
"no signal" otherwise. The CEC message goes out before the signal is cut
and after it is back, so the HDMI port is powered while CEC talks. sway
is the step that must work: when it fails, the change counts as failed
and the caller gets an error. A CEC failure is only reported in
`last_error`.

The bridge never switches the display on its own. A kiosk container that
restarts starts with the display on, and the page asks again.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Literal
from typing import Protocol

from src.host.cec import CecError
from src.host.sway import SwayError
from src.host.sysfs import drm_connectors
from src.host.sysfs import read_text
from src.infrastructure.logging.logger import log

Power = Literal["on", "off"]


class SwayPower(Protocol):
    async def get_power(self) -> bool | None: ...

    async def set_power(self, on: bool) -> None: ...


class CecPower(Protocol):
    def available(self) -> bool: ...

    async def set_power(self, on: bool) -> bool: ...


class DisplayPowerError(Exception):
    """sway could not switch the display."""


@dataclass(frozen=True)
class DisplayState:
    power: Power | None
    requested_power: Power | None
    changed_at: datetime | None
    sway_reachable: bool
    cec_available: bool
    cec_responding: bool | None
    last_error: str | None


class DisplayController:
    def __init__(self, sway: SwayPower, cec: CecPower, drm_dir: Path = Path("/sys/class/drm")):
        self._sway = sway
        self._cec = cec
        self._drm_dir = drm_dir
        self._lock = asyncio.Lock()
        self._requested: Power | None = None
        self._changed_at: datetime | None = None
        self._cec_responding: bool | None = None
        self._last_error: str | None = None

    async def state(self) -> DisplayState:
        """The power as sway reports it. Without sway, e.g. while the
        kiosk restarts, the kernel's power state of the connected
        displays stands in."""
        sway_reachable = True
        try:
            powered = await self._sway.get_power()
        except SwayError:
            sway_reachable = False
            powered = self._drm_power()
        power: Power | None = None if powered is None else ("on" if powered else "off")
        return DisplayState(
            power=power,
            requested_power=self._requested,
            changed_at=self._changed_at,
            sway_reachable=sway_reachable,
            cec_available=self._cec.available(),
            cec_responding=self._cec_responding,
            last_error=self._last_error,
        )

    async def set_power(self, power: Power) -> DisplayState:
        on = power == "on"
        async with self._lock:
            errors: list[str] = []
            cec_responding: bool | None = None
            sway_error: str | None = None
            if not on:
                cec_responding = await self._send_cec(on, errors)
            try:
                await self._sway.set_power(on)
            except SwayError as e:
                sway_error = str(e)
                errors.insert(0, sway_error)
            if on:
                cec_responding = await self._send_cec(on, errors)

            self._requested = power
            self._changed_at = datetime.now(UTC)
            self._cec_responding = cec_responding
            self._last_error = "; ".join(errors) or None
            if errors:
                log.warning("Display %s: %s", power, self._last_error)
            else:
                log.info("Display switched %s (CEC answered: %s).", power, cec_responding)
        if sway_error is not None:
            raise DisplayPowerError(sway_error)
        return await self.state()

    async def _send_cec(self, on: bool, errors: list[str]) -> bool | None:
        """True or False as the CEC client answers, None when the device
        has no CEC at all."""
        if not self._cec.available():
            return None
        try:
            return await self._cec.set_power(on)
        except CecError as e:
            errors.append(str(e))
            return True

    def _drm_power(self) -> bool | None:
        states: list[bool] = []
        for connector in drm_connectors(self._drm_dir):
            if read_text(connector / "status") != "connected":
                continue
            dpms = read_text(connector / "dpms")
            if dpms is not None:
                states.append(dpms.lower() == "on")
        if not states:
            return None
        return any(states)
