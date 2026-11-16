"""
src/api/identity.py

GET /identity and POST /identity/sign: hand this device's public key and
API key (src/identity/store.py) to the glados-frontend page running in
the kiosk, and sign the sign-in challenge glados-backend gives that page.
The private key never leaves the bridge, and the bridge checks nothing
about the credentials or the nonce beyond its format.

Both routes refuse a disallowed Origin outright rather than relying on
CORS alone (src/api/origins.py).

503 means the device has no usable identity (no store wired, or the
state directory is not usable). The page then shows that the device
cannot register, it never breaks.
"""

from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import Response
from pydantic import BaseModel
from pydantic import Field

from src.api.origins import require_allowed_origin
from src.identity.store import IdentityError
from src.identity.store import IdentityStore
from src.infrastructure.logging.logger import log

router = APIRouter(dependencies=[Depends(require_allowed_origin)])


class IdentityResponse(BaseModel):
    public_key: str
    api_key: str | None


class SignRequest(BaseModel):
    # The backend's challenge nonce. Only the format is checked: the
    # base64url alphabet plus "." keeps the signed bytes plain ASCII, and
    # the length bounds keep the bridge from signing anything that could
    # not be a nonce. The "." is there because the backend joins its
    # challenge from dot-separated parts (version, timestamp, random,
    # MAC); what they mean is the backend's business.
    nonce: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9._-]+$")


class SignResponse(BaseModel):
    signature: str


def _get_identity(request: Request) -> IdentityStore:
    store = cast(IdentityStore | None, request.app.state.identity)
    if store is None:
        raise HTTPException(status_code=503, detail="No device identity configured.")
    return store


def _unavailable(e: IdentityError) -> HTTPException:
    log.error("Device identity unavailable: %s", e)
    return HTTPException(status_code=503, detail="Device identity unavailable.")


@router.get("/identity")
def identity(request: Request, response: Response) -> IdentityResponse:
    store = _get_identity(request)
    try:
        public_key = store.public_key()
    except IdentityError as e:
        raise _unavailable(e) from e

    response.headers["Cache-Control"] = "no-store"
    return IdentityResponse(public_key=public_key, api_key=store.api_key)


@router.post("/identity/sign")
def sign(body: SignRequest, request: Request, response: Response) -> SignResponse:
    store = _get_identity(request)
    try:
        signature = store.sign(body.nonce)
    except IdentityError as e:
        raise _unavailable(e) from e

    response.headers["Cache-Control"] = "no-store"
    return SignResponse(signature=signature)
