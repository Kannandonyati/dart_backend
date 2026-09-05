"""Cross-cutting HTTP middleware: request correlation and security headers.

CORS, TrustedHost, and rate limiting are registered directly on the app in
main.py (they're first-class Starlette/slowapi integrations with their own
config surface); this module holds the two custom ones specific to DART.
"""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import set_request_path
from app.core.security import InvalidTokenError, TokenType, decode_token
from app.core.system_log import record_system_log, should_skip_request_log
from app.db.session import async_session_factory
from app.models.user import User

logger = structlog.get_logger(__name__)

_SKIP_USERLOG_STATUSES = {401, 403}


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Stamps every request with a request_id (accepted from an inbound
    X-Request-ID for trace continuity across services, otherwise generated),
    binds it into structlog's contextvars so every log line in the request
    carries it, and logs one line per request with timing."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        set_request_path(request.url.path)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        if response.status_code < 500:
            try:
                await _write_userlog(request, response.status_code, duration_ms, request_id)
            except Exception:
                logger.exception("system_log_userlog_failed")
        return response


async def _write_userlog(
    request: Request, status_code: int, duration_ms: float, request_id: str
) -> None:
    if should_skip_request_log(request.url.path, request.method):
        return
    if status_code in _SKIP_USERLOG_STATUSES:
        return
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
        user_id = uuid.UUID(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError):
        return
    try:
        async with async_session_factory() as session:
            user = await session.get(User, user_id)
    except Exception:
        logger.exception("system_log_user_lookup_failed")
        return
    if user is None:
        return
    level = "WARNING" if status_code >= 400 else "INFO"
    await record_system_log(
        log_name="userlog",
        logging_level=level,
        log_message=f"{request.method} {request.url.path}",
        request_url=request.url.path,
        request_id=request_id,
        username=user.username,
        user_email=user.email,
        actor_user_id=user.id,
        event_stage=_event_stage(request.url.path),
        time_taken=f"{duration_ms}ms",
    )


def _event_stage(path: str) -> str:
    parts = [part for part in path.split("/") if part and part != "api" and part != "v1"]
    return parts[0] if parts else "N/A"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline security headers on every response. This is not a
    substitute for a proper CSP tuned to the frontend's actual asset
    origins — that belongs in the reverse proxy/CDN config once the
    frontend's asset story is finalized — but it's the safe default for
    an API that also happens to serve docs/JSON."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response
