"""
src/api/debug.py

POST /debug/simulate: injects a simulated device event without any
hardware attached, so frontend development and demos can exercise the
whole event path (device -> bus -> /ws/events) on a machine with no RFID
reader or scanner attached. Only mounted by create_app() when DEBUG=true
(src/api/app.py) -- never reachable in a production build.
"""

from typing import Literal
from typing import cast

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel

from src.devices.manager import DeviceManager
from src.devices.mock import MockDevice

router = APIRouter()


class SimulateRequest(BaseModel):
    kind: Literal["rfid", "scanner"]
    value: str


def _get_manager(request: Request) -> DeviceManager:
    return cast(DeviceManager, request.app.state.manager)


def _find_mock(manager: DeviceManager) -> MockDevice:
    for device in manager.devices:
        if isinstance(device, MockDevice):
            return device
    raise HTTPException(
        status_code=409, detail="No mock device configured (set MOCK__ENABLED=true)."
    )


@router.post("/debug/simulate", status_code=202)
def simulate(payload: SimulateRequest, request: Request) -> dict[str, str]:
    mock = _find_mock(_get_manager(request))
    if payload.kind == "rfid":
        mock.simulate_rfid(payload.value)
    else:
        mock.simulate_scan(payload.value)
    return {"status": "accepted"}
