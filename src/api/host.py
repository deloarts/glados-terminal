"""
src/api/host.py

GET /display, POST /display and GET /device: the display's power for the
glados-frontend page that follows the schedule Glados sets, and this
device's details for the terminal list in Glados. The page decides when
the display is off and what the details mean; the bridge only switches
and reports (src/host/).

All three routes refuse a disallowed Origin like the identity routes do
(src/api/origins.py), since only the Glados page may switch the display
or read the device's serials. 503 means the part behind a route is not
available: no controller or reader wired, or sway could not switch the
display. Every answer carries `Cache-Control: no-store`, because each
one describes the device at that moment. The response shapes are
documented in docs/BRIDGE_API.md.
"""

import asyncio
from datetime import datetime
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import ConfigDict

from src.api.origins import require_allowed_origin
from src.host.device_info import DeviceInfoReader
from src.host.display import DisplayController
from src.host.display import DisplayPowerError
from src.host.display import DisplayState
from src.host.display import Power

router = APIRouter(dependencies=[Depends(require_allowed_origin)])


class _FromAttributes(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DisplayResponse(_FromAttributes):
    power: Power | None
    requested_power: Power | None
    changed_at: datetime | None
    sway_reachable: bool
    cec_available: bool
    cec_responding: bool | None
    last_error: str | None


class DisplayPowerRequest(BaseModel):
    power: Power


class EdidResponse(_FromAttributes):
    manufacturer_id: str | None
    make: str | None
    model: str | None
    product_code: int
    serial: str | None
    manufacture_year: int | None
    native_width: int | None
    native_height: int | None
    native_refresh_hz: float | None
    width_mm: int | None
    height_mm: int | None


class ConnectorResponse(_FromAttributes):
    connector: str
    connected: bool
    enabled: bool | None
    dpms: Power | None
    edid: EdidResponse | None


class ComputerResponse(_FromAttributes):
    model: str | None
    serial: str | None
    memory_total_bytes: int | None
    memory_installed_bytes: int | None
    kernel: str | None
    architecture: str
    cpu_temperature_celsius: float | None
    under_voltage: bool | None
    uptime_seconds: int | None


class HostResponse(_FromAttributes):
    hostname: str | None
    os_name: str | None
    os_id: str | None
    os_version_id: str | None


class DeviceResponse(BaseModel):
    computer: ComputerResponse
    host: HostResponse
    connectors: list[ConnectorResponse]
    display: DisplayResponse


def _display(request: Request) -> DisplayController:
    controller = cast(DisplayController | None, request.app.state.display)
    if controller is None:
        raise HTTPException(status_code=503, detail="No display control configured.")
    return controller


def _device_info(request: Request) -> DeviceInfoReader:
    reader = cast(DeviceInfoReader | None, request.app.state.device_info)
    if reader is None:
        raise HTTPException(status_code=503, detail="No device details configured.")
    return reader


def _display_response(state: DisplayState) -> DisplayResponse:
    return DisplayResponse.model_validate(state)


@router.get("/display")
async def get_display(request: Request, response: Response) -> DisplayResponse:
    state = await _display(request).state()
    response.headers["Cache-Control"] = "no-store"
    return _display_response(state)


@router.post("/display")
async def set_display(
    body: DisplayPowerRequest, request: Request, response: Response
) -> DisplayResponse:
    try:
        state = await _display(request).set_power(body.power)
    except DisplayPowerError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not switch the display {body.power}: {e}",
            headers={"Cache-Control": "no-store"},
        ) from e
    response.headers["Cache-Control"] = "no-store"
    return _display_response(state)


@router.get("/device")
async def get_device(request: Request, response: Response) -> DeviceResponse:
    reader = _device_info(request)
    controller = _display(request)
    info = await asyncio.to_thread(reader.read)
    state = await controller.state()
    response.headers["Cache-Control"] = "no-store"
    return DeviceResponse(
        computer=ComputerResponse.model_validate(info.computer),
        host=HostResponse.model_validate(info.host),
        connectors=[ConnectorResponse.model_validate(c) for c in info.connectors],
        display=_display_response(state),
    )
