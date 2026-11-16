"""
tests/fake_host.py

Builds a fake /proc, /sys and host /etc in a temporary directory, shaped
like what the bridge container sees on a Raspberry Pi 4 with a Samsung
S27D390 on its first HDMI port, for tests/test_device_info.py and
tests/test_host_api.py.
"""

from dataclasses import dataclass
from pathlib import Path

from tests.test_edid import SAMSUNG_S27D390


@dataclass(frozen=True)
class FakeHost:
    proc: Path
    sys: Path
    os_release: Path
    hostname: Path


def _write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)


def build_fake_host(root: Path) -> FakeHost:
    proc, sys, etc = root / "proc", root / "sys", root / "host-etc"

    _write(proc / "device-tree" / "model", "Raspberry Pi 4 Model B Rev 1.5\0")
    _write(proc / "device-tree" / "serial-number", "1000000012345678\0")
    _write(proc / "device-tree" / "system" / "linux,revision", bytes.fromhex("00c03115"))
    _write(proc / "meminfo", "MemTotal:        3835748 kB\nMemFree:         1000000 kB\n")
    _write(proc / "uptime", "20392.32 74400.69\n")
    _write(proc / "sys" / "kernel" / "osrelease", "6.18.50+rpt-rpi-v8\n")

    _write(sys / "class" / "thermal" / "thermal_zone0" / "type", "cpu-thermal\n")
    _write(sys / "class" / "thermal" / "thermal_zone0" / "temp", "49173\n")
    _write(sys / "class" / "hwmon" / "hwmon0" / "name", "cpu_thermal\n")
    _write(sys / "class" / "hwmon" / "hwmon1" / "name", "rpi_volt\n")
    _write(sys / "class" / "hwmon" / "hwmon1" / "in0_lcrit_alarm", "0\n")

    drm = sys / "class" / "drm"
    _write(drm / "card1-HDMI-A-1" / "status", "connected\n")
    _write(drm / "card1-HDMI-A-1" / "enabled", "enabled\n")
    _write(drm / "card1-HDMI-A-1" / "dpms", "On\n")
    _write(drm / "card1-HDMI-A-1" / "edid", SAMSUNG_S27D390)
    _write(drm / "card1-HDMI-A-2" / "status", "disconnected\n")
    _write(drm / "card1-HDMI-A-2" / "enabled", "disabled\n")
    _write(drm / "card1-HDMI-A-2" / "dpms", "On\n")
    _write(drm / "card1-HDMI-A-2" / "edid", b"")
    _write(drm / "card1-Writeback-1" / "status", "unknown\n")
    (drm / "renderD128").mkdir()

    _write(
        etc / "os-release",
        'PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nNAME="Debian GNU/Linux"\n'
        'VERSION_ID="13"\nID=debian\n',
    )
    _write(etc / "hostname", "kiosk-01\n")
    return FakeHost(proc=proc, sys=sys, os_release=etc / "os-release", hostname=etc / "hostname")
