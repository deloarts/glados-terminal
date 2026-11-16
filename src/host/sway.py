"""
src/host/sway.py

Switches the display's HDMI signal off and on through sway, the
compositor in the kiosk container, over sway's IPC socket. The kiosk
container keeps that socket in its runtime directory, which
docker-compose.yml shares with the bridge through a volume
(SYSTEM__SWAY_SOCKET_DIR inside the bridge).

The IPC protocol is i3's: a message is the magic string "i3-ipc", the
payload length and the message type as 32-bit integers in the host's
byte order, then a JSON payload. One connection per request keeps this
free of state, and a stale socket left by an earlier sway (one that no
longer accepts connections) is skipped for the next newest.

sway 1.8 renamed the output command `dpms` to `power`. The command word
follows the version sway reports, and the other word is tried once when
sway rejects the first, so the bridge works with either kiosk image.
"""

import asyncio
import json
import struct
from pathlib import Path
from typing import Any

_MAGIC = b"i3-ipc"
_HEADER = struct.Struct("=6sII")
_RUN_COMMAND = 0
_GET_OUTPUTS = 3
_GET_VERSION = 7


class SwayError(Exception):
    """sway could not be reached or refused the command."""


class SwayClient:
    def __init__(self, socket_dir: Path, timeout: float = 3.0) -> None:
        self._socket_dir = socket_dir
        self._timeout = timeout

    async def get_power(self) -> bool | None:
        """True when any display is powered, False when every one is off,
        None when sway reports no display. sway 1.8 and later report
        `power`, sway 1.7 reports `dpms`."""
        outputs = await self._request(_GET_OUTPUTS)
        states: list[bool] = []
        for output in outputs if isinstance(outputs, list) else []:
            if not isinstance(output, dict):
                continue
            state = output.get("power", output.get("dpms"))
            if isinstance(state, bool):
                states.append(state)
        if not states:
            return None
        return any(states)

    async def set_power(self, on: bool) -> None:
        state = "on" if on else "off"
        words = ["power", "dpms"] if await self._supports_power() else ["dpms", "power"]
        first_error = ""
        for word in words:
            replies = await self._request(_RUN_COMMAND, f"output * {word} {state}")
            error = _command_error(replies)
            if error is None:
                return
            first_error = first_error or error
        raise SwayError(f"sway refused to switch the display {state}: {first_error}")

    async def _supports_power(self) -> bool:
        reply = await self._request(_GET_VERSION)
        if not isinstance(reply, dict):
            return True
        major, minor = reply.get("major"), reply.get("minor")
        if not isinstance(major, int) or not isinstance(minor, int):
            return True
        return (major, minor) >= (1, 8)

    def _sockets(self) -> list[Path]:
        """Newest first: sway names its socket after its PID, so a
        restarted sway can leave an older one behind."""
        try:
            sockets = [p for p in self._socket_dir.glob("sway-ipc.*.sock") if p.is_socket()]
        except OSError:
            return []
        return sorted(sockets, key=lambda p: p.stat().st_mtime, reverse=True)

    async def _request(self, message_type: int, payload: str = "") -> Any:
        sockets = self._sockets()
        if not sockets:
            raise SwayError(f"No sway socket in {self._socket_dir}. Is the kiosk running?")
        last_error: OSError | None = None
        for path in sockets:
            try:
                return await asyncio.wait_for(
                    self._exchange(path, message_type, payload.encode()), self._timeout
                )
            except (ConnectionRefusedError, FileNotFoundError) as e:
                last_error = e
            except (OSError, TimeoutError, asyncio.IncompleteReadError) as e:
                raise SwayError(f"sway IPC at {path} failed: {e!r}") from e
        raise SwayError(f"sway does not answer on {self._socket_dir}: {last_error}")

    async def _exchange(self, path: Path, message_type: int, payload: bytes) -> Any:
        reader, writer = await asyncio.open_unix_connection(str(path))
        try:
            writer.write(_HEADER.pack(_MAGIC, len(payload), message_type) + payload)
            await writer.drain()
            magic, length, _ = _HEADER.unpack(await reader.readexactly(_HEADER.size))
            if magic != _MAGIC:
                raise SwayError(f"{path} does not speak the sway IPC protocol.")
            body = await reader.readexactly(length)
        finally:
            writer.close()
        try:
            return json.loads(body)
        except ValueError as e:
            raise SwayError(f"sway sent an unreadable reply: {e}") from e


def _command_error(replies: Any) -> str | None:
    """None when every command in the reply succeeded, else sway's error."""
    if not isinstance(replies, list) or not replies:
        return "empty reply"
    for reply in replies:
        if not isinstance(reply, dict) or reply.get("success") is not True:
            error = reply.get("error") if isinstance(reply, dict) else None
            return str(error or "command failed")
    return None
