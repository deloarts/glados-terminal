"""
tests/test_host_api.py

Coverage for GET /display, POST /display and GET /device
(src/api/host.py) with the display controller (src/host/display.py)
driving a fake sway and a fake CEC client, and the device reader over a
fake host (tests/fake_host.py). Includes the Origin check, which these
routes share with the identity routes.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.devices.manager import DeviceManager
from src.events.bus import EventBus
from src.host.cec import CecError
from src.host.device_info import DeviceInfoReader
from src.host.display import DisplayController
from src.host.sway import SwayError
from src.infrastructure.config import cfg
from tests.fake_host import FakeHost
from tests.fake_host import build_fake_host

ALLOWED = "https://glados.example.com"
DISALLOWED = "https://evil.example.com"


class FakeSway:
    def __init__(self) -> None:
        self.powered: bool | None = True
        self.reachable = True
        self.refuse = False
        self.log: list[str] = []

    async def get_power(self) -> bool | None:
        if not self.reachable:
            raise SwayError("No sway socket")
        return self.powered

    async def set_power(self, on: bool) -> None:
        if not self.reachable:
            raise SwayError("No sway socket in /run/kiosk. Is the kiosk running?")
        if self.refuse:
            raise SwayError("sway refused to switch the display")
        self.log.append(f"sway {'on' if on else 'off'}")
        self.powered = on


class FakeCec:
    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.has_adapter = True
        self.answers = True
        self.fails = False

    def available(self) -> bool:
        return self.has_adapter

    async def set_power(self, on: bool) -> bool:
        if self.fails:
            raise CecError("The display on /dev/cec0 did not take --standby.")
        if self.answers:
            self.log.append(f"cec {'on' if on else 'off'}")
        return self.answers


@pytest.fixture(autouse=True)
def _allow_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.bridge, "allowed_origins", [ALLOWED])


@pytest.fixture
def sway() -> FakeSway:
    return FakeSway()


@pytest.fixture
def cec(sway: FakeSway) -> FakeCec:
    return FakeCec(sway.log)


@pytest.fixture
def host(tmp_path: Path) -> FakeHost:
    return build_fake_host(tmp_path)


@pytest.fixture
def client(sway: FakeSway, cec: FakeCec, host: FakeHost) -> TestClient:
    bus = EventBus()
    reader = DeviceInfoReader(
        os_release_path=host.os_release,
        hostname_path=host.hostname,
        proc_dir=host.proc,
        sys_dir=host.sys,
    )
    display = DisplayController(sway=sway, cec=cec, drm_dir=host.sys / "class" / "drm")
    app = create_app(
        bus=bus, manager=DeviceManager(bus=bus, devices=[]), display=display, device_info=reader
    )
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {"Origin": ALLOWED}


def test_display_before_any_change(client: TestClient) -> None:
    response = client.get("/display", headers=_headers())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.json() == {
        "power": "on",
        "requested_power": None,
        "changed_at": None,
        "sway_reachable": True,
        "cec_available": True,
        "cec_responding": None,
        "last_error": None,
    }


def test_off_sends_cec_standby_before_cutting_the_signal(
    client: TestClient, sway: FakeSway
) -> None:
    response = client.post("/display", json={"power": "off"}, headers=_headers())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["power"] == "off"
    assert body["requested_power"] == "off"
    assert body["changed_at"] is not None
    assert body["cec_responding"] is True
    assert body["last_error"] is None
    assert sway.log == ["cec off", "sway off"]


def test_on_restores_the_signal_before_waking_over_cec(client: TestClient, sway: FakeSway) -> None:
    client.post("/display", json={"power": "off"}, headers=_headers())
    sway.log.clear()

    response = client.post("/display", json={"power": "on"}, headers=_headers())

    assert response.status_code == 200
    assert response.json()["power"] == "on"
    assert sway.log == ["sway on", "cec on"]


def test_a_display_without_cec_is_switched_by_sway_alone(
    client: TestClient, sway: FakeSway, cec: FakeCec
) -> None:
    cec.answers = False

    body = client.post("/display", json={"power": "off"}, headers=_headers()).json()

    assert body["power"] == "off"
    assert body["cec_available"] is True
    assert body["cec_responding"] is False
    assert body["last_error"] is None
    assert sway.log == ["sway off"]


def test_a_device_without_cec_adapter_reports_cec_unavailable(
    client: TestClient, cec: FakeCec
) -> None:
    cec.has_adapter = False

    body = client.post("/display", json={"power": "off"}, headers=_headers()).json()

    assert body["cec_available"] is False
    assert body["cec_responding"] is None


def test_a_cec_failure_is_reported_but_the_change_stands(
    client: TestClient, sway: FakeSway, cec: FakeCec
) -> None:
    cec.fails = True

    response = client.post("/display", json={"power": "off"}, headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["power"] == "off"
    assert "did not take --standby" in body["last_error"]


def test_a_sway_failure_is_a_503_and_stays_in_the_state(client: TestClient, sway: FakeSway) -> None:
    sway.refuse = True

    response = client.post("/display", json={"power": "off"}, headers=_headers())

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "Could not switch the display off" in response.json()["detail"]
    state = client.get("/display", headers=_headers()).json()
    assert state["power"] == "on"
    assert state["requested_power"] == "off"
    assert "refused" in state["last_error"]


def test_without_sway_the_kernel_power_state_stands_in(
    client: TestClient, sway: FakeSway, host: FakeHost
) -> None:
    sway.reachable = False
    (host.sys / "class" / "drm" / "card1-HDMI-A-1" / "dpms").write_text("Off\n")

    body = client.get("/display", headers=_headers()).json()

    assert body["sway_reachable"] is False
    assert body["power"] == "off"


@pytest.mark.parametrize("body", [{}, {"power": "standby"}, {"power": True}])
def test_an_invalid_power_is_a_422(client: TestClient, body: dict[str, object]) -> None:
    assert client.post("/display", json=body, headers=_headers()).status_code == 422


def test_device_reports_computer_host_connectors_and_display(client: TestClient) -> None:
    response = client.get("/device", headers=_headers())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"computer", "host", "connectors", "display"}
    assert body["computer"]["model"] == "Raspberry Pi 4 Model B Rev 1.5"
    assert body["computer"]["memory_installed_bytes"] == 4 * 1024**3
    assert body["computer"]["cpu_temperature_celsius"] == 49.2
    assert body["host"] == {
        "hostname": "kiosk-01",
        "os_name": "Debian GNU/Linux 13 (trixie)",
        "os_id": "debian",
        "os_version_id": "13",
    }
    assert body["connectors"][0] == {
        "connector": "HDMI-A-1",
        "connected": True,
        "enabled": True,
        "dpms": "on",
        "edid": {
            "manufacturer_id": "SAM",
            "make": "Samsung",
            "model": "S27D390",
            "product_code": 2919,
            "serial": "12345678",
            "manufacture_year": 2015,
            "native_width": 1920,
            "native_height": 1080,
            "native_refresh_hz": 60.0,
            "width_mm": 598,
            "height_mm": 336,
        },
    }
    assert body["connectors"][1]["connected"] is False
    assert body["display"]["power"] == "on"


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/display"), ("POST", "/display"), ("GET", "/device")],
)
def test_a_disallowed_origin_is_refused_before_anything_happens(
    client: TestClient, sway: FakeSway, method: str, path: str
) -> None:
    # No body at all: the 403 comes before the body would fail validation.
    response = client.request(method, path, headers={"Origin": DISALLOWED})

    assert response.status_code == 403
    assert sway.log == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("GET", "/display", None), ("POST", "/display", {"power": "off"}), ("GET", "/device", None)],
)
def test_a_missing_origin_is_allowed(
    client: TestClient, method: str, path: str, body: dict[str, str] | None
) -> None:
    assert client.request(method, path, json=body).status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("GET", "/display", None), ("POST", "/display", {"power": "off"}), ("GET", "/device", None)],
)
def test_nothing_wired_is_a_503(method: str, path: str, body: dict[str, str] | None) -> None:
    bus = EventBus()
    client = TestClient(create_app(bus=bus, manager=DeviceManager(bus=bus, devices=[])))

    response = client.request(method, path, json=body, headers=_headers())

    assert response.status_code == 503
