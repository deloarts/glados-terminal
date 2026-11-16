"""
tests/test_cec.py

Coverage for the CEC client (src/host/cec.py) with `cec-ctl` faked: the
runner answers with output in the format cec-ctl prints, so the tests pin
which output counts as "the TV answered" and "the TV took the command".
"""

from pathlib import Path

import pytest

from src.host.cec import CecClient
from src.host.cec import CecError

ANSWERED = """
Transmit from Playback Device 1 to TV (4 to 0):
CEC_MSG_GIVE_DEVICE_POWER_STATUS (0x8f)
    Received from TV (0):
    CEC_MSG_REPORT_POWER_STATUS (0x90):
\tpwr-state: on (0x00)
\tSequence: 12 Tx Timestamp: 1234.567s Rx Timestamp: 1234.600s
\tApproximate response time: 33 ms
"""

NOT_ANSWERED = """
Transmit from Playback Device 1 to TV (4 to 0):
CEC_MSG_GIVE_DEVICE_POWER_STATUS (0x8f)
\tSequence: 3 Tx Timestamp: 123.400s
\tTx, Not Acknowledged (4), Max Retries
"""

UNCONFIGURED = "\nAdapter is unconfigured, please configure it first.\n"

SENT = """
Transmit from Playback Device 1 to TV (4 to 0):
CEC_MSG_STANDBY (0x36)
\tSequence: 13 Tx Timestamp: 1240.100s
"""

NOT_TAKEN = """
Transmit from Playback Device 1 to TV (4 to 0):
CEC_MSG_STANDBY (0x36)
\tSequence: 13 Tx Timestamp: 1240.100s
\tTx, Not Acknowledged (4), Max Retries
"""


class FakeCecCtl:
    """Answers per adapter and per message from a table, records calls."""

    def __init__(self, answers: dict[tuple[str, str], list[str]]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    async def __call__(self, args: list[str], timeout: float) -> tuple[int, str]:
        self.calls.append(args)
        adapter = Path(args[args.index("--device") + 1]).name
        queue = self.answers.get((adapter, args[-1]), [""])
        return 0, queue.pop(0) if len(queue) > 1 else queue[0]


@pytest.fixture
def cec_ctl(tmp_path: Path) -> str:
    executable = tmp_path / "cec-ctl"
    executable.write_text("#!/bin/sh\n")
    executable.chmod(0o755)
    return str(executable)


def _client(tmp_path: Path, cec_ctl: str, fake: FakeCecCtl, adapters: list[str]) -> CecClient:
    dev = tmp_path / "dev"
    dev.mkdir()
    for name in adapters:
        (dev / name).touch()
    return CecClient(dev_dir=dev, executable=cec_ctl, runner=fake)


async def test_standby_goes_to_the_adapter_whose_tv_answers(tmp_path: Path, cec_ctl: str) -> None:
    fake = FakeCecCtl(
        {
            ("cec0", "--give-device-power-status"): [NOT_ANSWERED],
            ("cec1", "--give-device-power-status"): [ANSWERED],
            ("cec1", "--standby"): [SENT],
        }
    )
    client = _client(tmp_path, cec_ctl, fake, ["cec0", "cec1"])

    assert await client.set_power(False) is True
    assert [(Path(c[2]).name, c[-1]) for c in fake.calls] == [
        ("cec0", "--give-device-power-status"),
        ("cec1", "--give-device-power-status"),
        ("cec1", "--standby"),
    ]
    assert all(c[3:5] == ["--skip-info", "--to"] for c in fake.calls)


async def test_wake_sends_image_view_on(tmp_path: Path, cec_ctl: str) -> None:
    fake = FakeCecCtl(
        {
            ("cec0", "--give-device-power-status"): [ANSWERED],
            ("cec0", "--image-view-on"): [SENT],
        }
    )
    client = _client(tmp_path, cec_ctl, fake, ["cec0"])

    assert await client.set_power(True) is True
    assert fake.calls[-1][-3:] == ["--to", "0", "--image-view-on"]


async def test_nothing_answering_sends_nothing(tmp_path: Path, cec_ctl: str) -> None:
    fake = FakeCecCtl({("cec0", "--give-device-power-status"): [NOT_ANSWERED]})
    client = _client(tmp_path, cec_ctl, fake, ["cec0"])

    assert await client.set_power(False) is False
    assert all(c[-1] == "--give-device-power-status" for c in fake.calls)


async def test_an_unconfigured_adapter_is_claimed_as_playback_device(
    tmp_path: Path, cec_ctl: str
) -> None:
    fake = FakeCecCtl(
        {
            ("cec0", "--give-device-power-status"): [UNCONFIGURED, ANSWERED],
            ("cec0", "--standby"): [SENT],
        }
    )
    client = _client(tmp_path, cec_ctl, fake, ["cec0"])

    assert await client.set_power(False) is True
    assert "--playback" not in fake.calls[0]
    assert "--playback" in fake.calls[1]
    assert "--playback" not in fake.calls[2]


async def test_a_tv_that_answers_but_does_not_take_the_command_is_an_error(
    tmp_path: Path, cec_ctl: str
) -> None:
    fake = FakeCecCtl(
        {
            ("cec0", "--give-device-power-status"): [ANSWERED],
            ("cec0", "--standby"): [NOT_TAKEN],
        }
    )
    client = _client(tmp_path, cec_ctl, fake, ["cec0"])

    with pytest.raises(CecError, match="did not take --standby"):
        await client.set_power(False)


async def test_a_failing_cec_ctl_counts_as_not_answering(tmp_path: Path, cec_ctl: str) -> None:
    async def broken(args: list[str], timeout: float) -> tuple[int, str]:
        raise TimeoutError

    client = _client(tmp_path, cec_ctl, FakeCecCtl({}), ["cec0"])
    client._runner = broken

    assert await client.set_power(False) is False


def test_availability_needs_an_adapter_and_cec_ctl(tmp_path: Path, cec_ctl: str) -> None:
    with_adapter = _client(tmp_path, cec_ctl, FakeCecCtl({}), ["cec0"])
    assert with_adapter.available() is True

    without_tool = CecClient(dev_dir=tmp_path / "dev", executable=str(tmp_path / "missing"))
    assert without_tool.available() is False

    empty = tmp_path / "empty"
    empty.mkdir()
    assert CecClient(dev_dir=empty, executable=cec_ctl).available() is False
