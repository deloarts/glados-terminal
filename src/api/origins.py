"""
src/api/origins.py

The server-side half of the browser origin allowlist
(BRIDGE__ALLOWED_ORIGINS). CORS only stops a disallowed page from
reading a response, and WebSockets ignore CORS entirely, so the routes
that hand out device events or credentials check the Origin header
themselves as well.

`require_allowed_origin` is that check as a router dependency, for the
identity, display and device routes. It runs before the request body is
validated, so a foreign page gets a 403 whatever it sends, never a 422
that tells it something about this API.
"""

from fastapi import HTTPException
from fastapi import Request

from src.infrastructure.config import cfg
from src.infrastructure.logging.logger import log


def origin_allowed(origin: str | None) -> bool:
    """
    A browser always sends `Origin` on these requests; a non-browser
    client (curl, the test suite, the smoke script in docs/DEVELOPMENT.md)
    sends none. A missing Origin therefore cannot be a cross-origin
    browser attack and is allowed. A local process on this device could
    reach the bridge whatever we check here, so refusing it would cost
    tooling and buy nothing. A *present* Origin must be on the allowlist.
    """
    if origin is None:
        return True
    return origin in cfg.bridge.allowed_origins


def require_allowed_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin_allowed(origin):
        log.warning("Refused %s request from disallowed origin %r.", request.url.path, origin)
        raise HTTPException(status_code=403, detail="Origin not allowed.")
