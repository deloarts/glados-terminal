"""
tests/test_device_info.py

Coverage for the device details reader (src/host/device_info.py) over a
fake /proc, /sys and host /etc (tests/fake_host.py).
"""

import os
from pathlib import Path

from src.host.device_info import DeviceInfoReader
from tests.fake_host import FakeHost
from tests.fake_host import build_fake_host


def _reader(host: FakeHost) -> DeviceInfoReader:
    return DeviceInfoReader(
        os_release_path=host.os_release,
        hostname_path=host.hostname,
        proc_dir=host.proc,
        sys_dir=host.sys,
    )


def test_reads_a_raspberry_pi_with_a_samsung_monitor(tmp_path: Path) -> None:
    info = _reader(build_fake_host(tmp_path)).read()

    computer = info.computer
    assert computer.model == "Raspberry Pi 4 Model B Rev 1.5"
    assert computer.serial == "1000000012345678"
    assert computer.memory_total_bytes == 3835748 * 1024
    assert computer.memory_installed_bytes == 4 * 1024**3
    assert computer.kernel == "6.18.50+rpt-rpi-v8"
    assert computer.architecture == os.uname().machine
    assert computer.cpu_temperature_celsius == 49.2
    assert computer.under_voltage is False
    assert computer.uptime_seconds == 20392

    assert info.host.hostname == "kiosk-01"
    assert info.host.os_name == "Debian GNU/Linux 13 (trixie)"
    assert info.host.os_id == "debian"
    assert info.host.os_version_id == "13"

    assert [c.connector for c in info.connectors] == ["HDMI-A-1", "HDMI-A-2"]
    hdmi1, hdmi2 = info.connectors
    assert (hdmi1.connected, hdmi1.enabled, hdmi1.dpms) == (True, True, "on")
    assert hdmi1.edid is not None
    assert (hdmi1.edid.make, hdmi1.edid.model) == ("Samsung", "S27D390")
    assert (hdmi2.connected, hdmi2.enabled, hdmi2.dpms, hdmi2.edid) == (False, False, None, None)


def test_static_facts_are_read_once_and_live_ones_on_every_call(tmp_path: Path) -> None:
    host = build_fake_host(tmp_path)
    reader = _reader(host)

    host.hostname.write_text("renamed\n")
    (host.proc / "sys" / "kernel" / "osrelease").write_text("7.0.0\n")
    (host.sys / "class" / "thermal" / "thermal_zone0" / "temp").write_text("71500\n")
    (host.sys / "class" / "hwmon" / "hwmon1" / "in0_lcrit_alarm").write_text("1\n")
    (host.proc / "uptime").write_text("30000.99 1.0\n")
    (host.sys / "class" / "drm" / "card1-HDMI-A-1" / "dpms").write_text("Off\n")
    info = reader.read()

    assert info.host.hostname == "kiosk-01"
    assert info.computer.kernel == "6.18.50+rpt-rpi-v8"
    assert info.computer.cpu_temperature_celsius == 71.5
    assert info.computer.under_voltage is True
    assert info.computer.uptime_seconds == 30000
    assert info.connectors[0].dpms == "off"


def test_missing_files_are_unknown_not_errors(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    reader = DeviceInfoReader(
        os_release_path=empty / "os-release",
        hostname_path=empty / "hostname",
        proc_dir=empty / "proc",
        sys_dir=empty / "sys",
    )

    info = reader.read()

    assert info.computer.model is None
    assert info.computer.serial is None
    assert info.computer.memory_total_bytes is None
    assert info.computer.memory_installed_bytes is None
    assert info.computer.cpu_temperature_celsius is None
    assert info.computer.under_voltage is None
    assert info.computer.uptime_seconds is None
    assert info.host.hostname is None
    assert info.host.os_name is None
    assert info.connectors == []


def test_a_board_without_device_tree_is_named_by_dmi(tmp_path: Path) -> None:
    dmi = tmp_path / "sys" / "class" / "dmi" / "id"
    dmi.mkdir(parents=True)
    (dmi / "sys_vendor").write_text("Intel Corporation\n")
    (dmi / "product_name").write_text("NUC8i5BEH\n")
    (dmi / "product_serial").write_text("G6BE12345\n")

    info = DeviceInfoReader(
        os_release_path=tmp_path / "os-release",
        hostname_path=tmp_path / "hostname",
        proc_dir=tmp_path / "proc",
        sys_dir=tmp_path / "sys",
    ).read()

    assert info.computer.model == "Intel Corporation NUC8i5BEH"
    assert info.computer.serial == "G6BE12345"
    assert info.computer.memory_installed_bytes is None
