"""
src/host/device_info.py

What this device is, for the terminal list in Glados (GET /device): the
computer (model, serial, RAM, kernel, CPU temperature, under-voltage,
uptime), the host's operating system and hostname, and every display
connector with the facts its EDID gives about the display behind it.

The bridge container shares the host's kernel, so /proc and /sys
describe the device itself. Its /etc does not: /etc/os-release and
/etc/hostname inside the container describe the bridge image. The host's
copies are mounted read-only into the container instead (see
docker-compose.yml), and are reported as unknown when they are missing,
never replaced by the container's own.

Facts that cannot change while the device runs are read once, when the
reader is created. Temperature, under-voltage, uptime and the display
connectors (a display can be swapped) are read on every call. Nothing
here raises for a missing file: a board or kernel that lacks one simply
reports that field as None.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.host.edid import EdidInfo
from src.host.edid import parse_edid
from src.host.sysfs import connector_name
from src.host.sysfs import drm_connectors
from src.host.sysfs import read_bytes
from src.host.sysfs import read_text


@dataclass(frozen=True)
class ComputerInfo:
    model: str | None
    serial: str | None
    memory_total_bytes: int | None
    memory_installed_bytes: int | None
    kernel: str | None
    architecture: str
    cpu_temperature_celsius: float | None
    under_voltage: bool | None
    uptime_seconds: int | None


@dataclass(frozen=True)
class HostInfo:
    hostname: str | None
    os_name: str | None
    os_id: str | None
    os_version_id: str | None


@dataclass(frozen=True)
class ConnectorInfo:
    connector: str
    connected: bool
    enabled: bool | None
    dpms: Literal["on", "off"] | None
    edid: EdidInfo | None


@dataclass(frozen=True)
class DeviceInfo:
    computer: ComputerInfo
    host: HostInfo
    connectors: list[ConnectorInfo]


@dataclass(frozen=True)
class _StaticFacts:
    model: str | None
    serial: str | None
    memory_total_bytes: int | None
    memory_installed_bytes: int | None
    kernel: str | None
    architecture: str
    host: HostInfo


class DeviceInfoReader:
    def __init__(
        self,
        os_release_path: Path,
        hostname_path: Path,
        proc_dir: Path = Path("/proc"),
        sys_dir: Path = Path("/sys"),
    ) -> None:
        self._proc = proc_dir
        self._sys = sys_dir
        self._static = self._read_static(os_release_path, hostname_path)

    def read(self) -> DeviceInfo:
        static = self._static
        computer = ComputerInfo(
            model=static.model,
            serial=static.serial,
            memory_total_bytes=static.memory_total_bytes,
            memory_installed_bytes=static.memory_installed_bytes,
            kernel=static.kernel,
            architecture=static.architecture,
            cpu_temperature_celsius=self._cpu_temperature(),
            under_voltage=self._under_voltage(),
            uptime_seconds=self._uptime(),
        )
        return DeviceInfo(computer=computer, host=static.host, connectors=self._connectors())

    def _read_static(self, os_release_path: Path, hostname_path: Path) -> _StaticFacts:
        device_tree = self._proc / "device-tree"
        model = read_text(device_tree / "model")
        serial = read_text(device_tree / "serial-number")
        if model is None:
            # Not a device-tree board, e.g. a mini PC: the firmware's DMI
            # tables name it instead.
            dmi = self._sys / "class" / "dmi" / "id"
            parts = [read_text(dmi / "sys_vendor"), read_text(dmi / "product_name")]
            model = " ".join(p for p in parts if p) or None
            serial = serial or read_text(dmi / "product_serial")
        os_release = _parse_os_release(read_text(os_release_path) or "")
        return _StaticFacts(
            model=model,
            serial=serial,
            memory_total_bytes=self._memory_total(),
            memory_installed_bytes=_pi_memory(
                model, read_bytes(device_tree / "system" / "linux,revision")
            ),
            kernel=read_text(self._proc / "sys" / "kernel" / "osrelease"),
            architecture=os.uname().machine,
            host=HostInfo(
                hostname=read_text(hostname_path),
                os_name=os_release.get("PRETTY_NAME") or os_release.get("NAME"),
                os_id=os_release.get("ID"),
                os_version_id=os_release.get("VERSION_ID"),
            ),
        )

    def _memory_total(self) -> int | None:
        """MemTotal is what the kernel can use, a little less than what
        is installed, since firmware and GPU keep their share."""
        for line in (read_text(self._proc / "meminfo") or "").splitlines():
            name, _, value = line.partition(":")
            if name == "MemTotal":
                parts = value.split()
                if parts and parts[0].isdigit():
                    return int(parts[0]) * 1024
        return None

    def _cpu_temperature(self) -> float | None:
        """The thermal zone named after the CPU or SoC, else the first."""
        zones = sorted((self._sys / "class" / "thermal").glob("thermal_zone*"))
        preferred = [
            z for z in zones if any(k in (read_text(z / "type") or "") for k in ("cpu", "soc"))
        ]
        for zone in preferred + zones:
            value = read_text(zone / "temp")
            if value is not None and value.lstrip("-").isdigit():
                return round(int(value) / 1000, 1)
        return None

    def _under_voltage(self) -> bool | None:
        """The Raspberry Pi firmware's under-voltage alarm, exposed by the
        rpi_volt hwmon driver. None on boards without it."""
        for hwmon in sorted((self._sys / "class" / "hwmon").glob("hwmon*")):
            if read_text(hwmon / "name") == "rpi_volt":
                alarm = read_text(hwmon / "in0_lcrit_alarm")
                if alarm in ("0", "1"):
                    return alarm == "1"
        return None

    def _uptime(self) -> int | None:
        value = read_text(self._proc / "uptime")
        try:
            return int(float(value.split()[0])) if value else None
        except ValueError:
            return None

    def _connectors(self) -> list[ConnectorInfo]:
        result = []
        for path in drm_connectors(self._sys / "class" / "drm"):
            connected = read_text(path / "status") == "connected"
            enabled = read_text(path / "enabled")
            # An empty port reports "On" as well, which means nothing.
            dpms = read_text(path / "dpms") if connected else None
            edid = read_bytes(path / "edid")
            result.append(
                ConnectorInfo(
                    connector=connector_name(path),
                    connected=connected,
                    enabled=None if enabled is None else enabled == "enabled",
                    dpms=None if dpms is None else ("on" if dpms.lower() == "on" else "off"),
                    edid=parse_edid(edid) if edid else None,
                )
            )
        return result


def _parse_os_release(text: str) -> dict[str, str]:
    """KEY=value lines, values optionally in single or double quotes."""
    result: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if not sep or key.startswith("#"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        result[key] = value
    return result


def _pi_memory(model: str | None, revision: bytes | None) -> int | None:
    """A Raspberry Pi's installed RAM, from the memory size field of its
    revision code (new-style codes only): 256 MiB shifted left by the
    field's value."""
    if not model or not model.startswith("Raspberry Pi") or not revision or len(revision) != 4:
        return None
    code = int.from_bytes(revision, "big")
    if not code & (1 << 23):
        return None
    return (256 * 1024 * 1024) << ((code >> 20) & 0x7)
