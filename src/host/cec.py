"""
src/host/cec.py

Puts a TV into standby and wakes it again over HDMI-CEC, with `cec-ctl`
from v4l-utils (installed in the bridge image). Cutting the HDMI signal
alone leaves many TVs on, showing "no signal", so the display controller
(src/host/display.py) sends CEC as well whenever a display answers on it.

A Raspberry Pi has one CEC adapter per HDMI port (/dev/cec0, /dev/cec1).
Each is asked for the TV's power status first; the first adapter whose
TV answers gets the command, and an adapter where nothing answers (an
empty port, a monitor without CEC) is skipped. When nothing answers at
all, that is no error: the display is simply one without CEC.

The kernel keeps an adapter's logical address once it is claimed, so the
bridge claims one (as a playback device) only when `cec-ctl` reports the
adapter as unconfigured, e.g. after a reboot.

What `cec-ctl` prints is matched on its fixed English output: "Received
from" appears only when the TV replied, "Tx Timestamp" once a message
went out, and a status line starting with "Tx," only when it was not
acknowledged.
"""

import asyncio
import re
import shutil
from collections.abc import Awaitable
from collections.abc import Callable
from pathlib import Path

from src.infrastructure.logging.logger import log

# Runs a command and returns its exit code and its combined output.
Runner = Callable[[list[str], float], Awaitable[tuple[int, str]]]

_TV = "0"
_FAILED_STATUS = re.compile(r"^\s*Tx,", re.MULTILINE)


class CecError(Exception):
    """A display answered on CEC but did not take the command."""


async def run_command(args: list[str], timeout: float) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    return process.returncode or 0, stdout.decode(errors="replace")


class CecClient:
    def __init__(
        self,
        dev_dir: Path = Path("/dev"),
        executable: str = "cec-ctl",
        runner: Runner = run_command,
        timeout: float = 10.0,
    ) -> None:
        self._dev_dir = dev_dir
        self._executable = executable
        self._runner = runner
        self._timeout = timeout

    def adapters(self) -> list[Path]:
        try:
            return sorted(self._dev_dir.glob("cec[0-9]*"))
        except OSError:
            return []

    def available(self) -> bool:
        """A CEC adapter exists and `cec-ctl` is installed. Whether a
        display answers on it is only known once a command was sent."""
        return bool(self.adapters()) and shutil.which(self._executable) is not None

    async def set_power(self, on: bool) -> bool:
        """Sends image-view-on or standby to the first TV that answers.
        True when one answered and took it, False when none answered."""
        if not self.available():
            return False
        message = "--image-view-on" if on else "--standby"
        for adapter in self.adapters():
            if not await self._display_answers(adapter):
                continue
            code, output = await self._cec_ctl(adapter, "--to", _TV, message)
            if code != 0 or "Tx Timestamp" not in output or _FAILED_STATUS.search(output):
                raise CecError(f"The display on {adapter} did not take {message}.")
            log.info("Sent CEC %s on %s.", message, adapter)
            return True
        return False

    async def _display_answers(self, adapter: Path) -> bool:
        query = ("--to", _TV, "--give-device-power-status")
        code, output = await self._cec_ctl(adapter, *query)
        if "unconfigured" in output:
            code, output = await self._cec_ctl(adapter, "--playback", *query)
        return "Received from" in output

    async def _cec_ctl(self, adapter: Path, *args: str) -> tuple[int, str]:
        command = [self._executable, "--device", str(adapter), "--skip-info", *args]
        try:
            return await self._runner(command, self._timeout)
        except (OSError, TimeoutError) as e:
            log.warning("cec-ctl on %s failed: %r", adapter, e)
            return 1, ""
