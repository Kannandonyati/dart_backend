"""Write operational Maintenance logs without riding a request session.

Middleware and exception handlers run after the request session may
already be committed or rolled back, so every write here opens its own
short-lived session. A failed log insert must never fail the HTTP
response the user already got.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from app.db.session import async_session_factory
from app.models.system_log import SystemLog
from app.models.user import User

logger = structlog.get_logger(__name__)

MAINTENANCE_USER_TYPES = frozenset(
    {"Account Admin", "Department Admin", "Team Admin", "Group Owner"}
)

_SKIP_PATH_PREFIXES = (
    "/api/v1/health",
    "/api/v1/system-logs",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def can_read_system_logs(user: User) -> bool:
    types = set(user.user_types or [])
    return user.is_superuser or bool(MAINTENANCE_USER_TYPES & types)


def should_skip_request_log(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in _SKIP_PATH_PREFIXES)


async def record_system_log(
    *,
    log_name: str,
    logging_level: str,
    log_message: str,
    request_url: str | None = None,
    request_id: str | None = None,
    username: str | None = None,
    user_email: str | None = None,
    recon_name: str | None = None,
    event_stage: str | None = None,
    time_taken: str | None = None,
    variable_state: dict[str, Any] | None = None,
    actor_user_id: uuid.UUID | None = None,
    recon_id: uuid.UUID | None = None,
) -> None:
    try:
        async with async_session_factory() as session:
            session.add(
                SystemLog(
                    log_name=log_name,
                    logging_level=logging_level,
                    log_message=log_message,
                    request_url=request_url,
                    request_id=request_id,
                    username=username,
                    user_email=user_email,
                    recon_name=recon_name,
                    event_stage=event_stage,
                    time_taken=time_taken,
                    variable_state=variable_state,
                    actor_user_id=actor_user_id,
                    recon_id=recon_id,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("system_log_write_failed", log_name=log_name)
