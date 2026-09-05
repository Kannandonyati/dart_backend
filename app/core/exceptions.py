"""Application exception types and their FastAPI handlers.

The rule this module exists to enforce: an unhandled exception must never
put a stack trace, a SQL fragment, or an internal file path into an HTTP
response — that's an information-disclosure bug, not just an ugly error
page. Every response goes through the same envelope shape so the frontend
never has to branch on "which kind of error shape is this."
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.system_log import record_system_log

logger = structlog.get_logger(__name__)


class AppError(Exception):
    """Base class for application-raised errors with a stable error code.

    `code` is a machine-readable string the frontend can branch on
    (e.g. "recon_locked"); `message` is safe to show a user as-is.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "app_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        self.message = message
        if code:
            self.code = code
        super().__init__(message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "permission_denied"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


def _error_envelope(*, code: str, message: str, request_id: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "request_id": request_id}}


async def _write_error_system_log(request: Request, exc: Exception, request_id: str) -> None:
    path = request.url.path
    parts = [part for part in path.split("/") if part and part not in {"api", "v1"}]
    await record_system_log(
        log_name="dblog" if isinstance(exc, SQLAlchemyError) else "techlog",
        logging_level="ERROR",
        log_message=str(exc) or exc.__class__.__name__,
        request_url=path,
        request_id=request_id,
        event_stage=parts[0] if parts else "N/A",
        variable_state={"exception": exc.__class__.__name__},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(code=exc.code, message=exc.message, request_id=request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        # A field_validator that raises a plain ValueError (the normal,
        # documented way to fail Pydantic validation from custom logic —
        # see app/schemas/user.py's password check) causes Pydantic to
        # embed that raw exception *instance* in each error's ctx dict.
        # jsonable_encoder is what turns that into a plain string instead
        # of crashing json.dumps with "Object of type ValueError is not
        # JSON serializable" — passing exc.errors() to JSONResponse
        # directly looks fine until the first custom validator fires.
        details = jsonable_encoder(exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_envelope(
                code="validation_error",
                message="The request body did not match the expected shape.",
                request_id=request_id,
            )
            | {"details": details},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(
                code="http_error", message=str(exc.detail), request_id=request_id
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        # Full detail goes to the log (with request_id to correlate); the
        # client gets a generic message. This is the one place a stack
        # trace is allowed to exist, and it's server-side only.
        logger.exception("unhandled_exception", request_id=request_id)
        await _write_error_system_log(request, exc, request_id)
        message = str(exc) if settings.debug else "An unexpected error occurred."
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_envelope(code="internal_error", message=message, request_id=request_id),
        )
