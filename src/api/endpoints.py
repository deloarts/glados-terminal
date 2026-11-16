"""
src/api/endpoints.py

Plain read-only status endpoints. No auth, no business logic (see
CLAUDE.md) -- this is device I/O plumbing; the frontend and backend own
every decision made from what these report.
"""

from typing import cast

from fastapi import APIRouter
from fastapi import Request
from pydantic import BaseModel

from src.const import VERSION
from src.devices.manager import DeviceManager

router = APIRouter()


class DeviceStatusResponse(BaseModel):
    name: str
    status: str


class HealthResponse(BaseModel):
    status: str
    version: str
    devices: list[DeviceStatusResponse]


def _get_manager(request: Request) -> DeviceManager:
    return cast(DeviceManager, request.app.state.manager)


def _device_statuses(manager: DeviceManager) -> list[DeviceStatusResponse]:
    return [DeviceStatusResponse(name=d.name, status=d.status) for d in manager.devices]


@router.get("/health")
def health(request: Request) -> HealthResponse:
    manager = _get_manager(request)
    return HealthResponse(status="ok", version=VERSION, devices=_device_statuses(manager))


@router.get("/devices")
def devices(request: Request) -> list[DeviceStatusResponse]:
    return _device_statuses(_get_manager(request))
