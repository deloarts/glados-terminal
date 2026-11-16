"""
tests/test_sway.py

Coverage for the sway IPC client (src/host/sway.py) against a fake sway:
a Unix socket server in tmp_path that speaks the i3 IPC framing, answers
GET_VERSION with a configurable version and runs `output * <word> <state>`
commands the way sway 1.7 (`dpms` only) or 1.8 and later (`power`, with
`dpms` still accepted) do.
"""

import asyncio
import json
import os
import socket
import struct
from pathlib import Path

import pytest

from src.host.sway import SwayClient
from src.host.sway import SwayError

_HEADER = struct.Struct("=6sII")


class FakeSway:
    def __init__(self, version: tuple[int, int], words: tuple[str, ...]) -> None:
        self.version = version
        self.words = words
        self.power = True
        self.commands: list[str] = []

    def reply(self, message_type: int, payload: str) -> object:
        if message_type == 7:
            return {"major": self.version[0], "minor": self.version[1], "patch": 0}
        if message_type == 3:
            key = "power" if "power" in self.words else "dpms"
            return [{"name": "HDMI-A-1", "active": True, key: self.power}]
        self.commands.append(payload)
        _, _, word, state = payload.split()
        if word not in self.words:
            return [{"success": False, "parse_error": True, "error": f"Invalid {word}"}]
        self.power = state == "on"
        return [{"success": True}]

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        magic, length, message_type = _HEADER.unpack(await reader.readexactly(_HEADER.size))
        payload = (await reader.readexactly(length)).decode()
        body = json.dumps(self.reply(message_type, payload)).encode()
        writer.write(_HEADER.pack(magic, len(body), message_type) + body)
        await writer.drain()
        writer.close()


async def _serve(directory: Path, fake: FakeSway, pid: int = 1) -> asyncio.Server:
    return await asyncio.start_unix_server(
        fake.handle, path=str(directory / f"sway-ipc.10001.{pid}.sock")
    )


async def test_sway_1_10_is_switched_with_power(tmp_path: Path) -> None:
    fake = FakeSway((1, 10), ("power", "dpms"))
    async with await _serve(tmp_path, fake):
        client = SwayClient(tmp_path)

        await client.set_power(False)
        assert await client.get_power() is False
        await client.set_power(True)
        assert await client.get_power() is True

    assert fake.commands == ["output * power off", "output * power on"]


async def test_sway_1_7_is_switched_with_dpms(tmp_path: Path) -> None:
    fake = FakeSway((1, 7), ("dpms",))
    async with await _serve(tmp_path, fake):
        client = SwayClient(tmp_path)

        await client.set_power(False)
        assert await client.get_power() is False

    assert fake.commands == ["output * dpms off"]


async def test_the_other_word_is_tried_when_sway_refuses_the_first(tmp_path: Path) -> None:
    # Reports 1.8 but only knows dpms, as a patched build might.
    fake = FakeSway((1, 8), ("dpms",))
    async with await _serve(tmp_path, fake):
        await SwayClient(tmp_path).set_power(False)

    assert fake.commands == ["output * power off", "output * dpms off"]
    assert fake.power is False


async def test_refused_by_both_words_is_an_error(tmp_path: Path) -> None:
    fake = FakeSway((1, 10), ())
    async with await _serve(tmp_path, fake):
        with pytest.raises(SwayError, match="refused"):
            await SwayClient(tmp_path).set_power(False)


async def test_no_socket_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(SwayError, match="No sway socket"):
        await SwayClient(tmp_path).get_power()
    with pytest.raises(SwayError):
        await SwayClient(tmp_path / "missing").set_power(True)


async def test_a_stale_socket_is_skipped(tmp_path: Path) -> None:
    fake = FakeSway((1, 10), ("power", "dpms"))
    # A socket file nobody listens on, as an earlier sway leaves behind,
    # newer than the live one so it is tried first.
    async with await _serve(tmp_path, fake, pid=1):
        stale = socket.socket(socket.AF_UNIX)
        stale.bind(str(tmp_path / "sway-ipc.10001.2.sock"))
        stale.close()
        live = tmp_path / "sway-ipc.10001.1.sock"
        os.utime(live, (1_000_000_000, 1_000_000_000))

        assert await SwayClient(tmp_path).get_power() is True


async def test_no_outputs_is_unknown(tmp_path: Path) -> None:
    fake = FakeSway((1, 10), ("power",))
    fake.reply = lambda message_type, payload: []  # type: ignore[method-assign]
    async with await _serve(tmp_path, fake):
        assert await SwayClient(tmp_path).get_power() is None
