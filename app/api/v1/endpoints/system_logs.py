"""Maintenance system-log reads — old Dart POST /logs/all_logs + export.

Mounted at /api/v1/system-logs.
"""

import csv
import io
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.exceptions import PermissionDeniedError
from app.core.system_log import can_read_system_logs
from app.models.system_log import SystemLog
from app.schemas.pagination import PaginatedResponse, build_pagination_meta
from app.schemas.system_log import SystemLogRead

router = APIRouter(prefix="/system-logs", tags=["system-logs"])


_EXPORT_COLUMNS = [
    "created_at",
    "log_name",
    "logging_level",
    "recon_name",
    "username",
    "user_email",
    "event_stage",
    "log_message",
    "request_url",
    "request_id",
    "time_taken",
]


def _require_maintenance_reader(current_user: CurrentUser) -> None:
    if not can_read_system_logs(current_user):
        raise PermissionDeniedError("Only a maintenance admin may view system logs.")


def _filtered_stmt(
    *,
    log_name: str | None,
    logging_level: str | None,
):
    stmt = select(SystemLog)
    if log_name:
        stmt = stmt.where(SystemLog.log_name == log_name)
    if logging_level:
        stmt = stmt.where(SystemLog.logging_level == logging_level.upper())
    return stmt


@router.get("", response_model=PaginatedResponse[SystemLogRead])
async def list_system_logs(
    current_user: CurrentUser,
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
    log_name: Annotated[str | None, Query()] = None,
    logging_level: Annotated[str | None, Query()] = None,
) -> PaginatedResponse[SystemLogRead]:
    _require_maintenance_reader(current_user)
    filtered = _filtered_stmt(log_name=log_name, logging_level=logging_level)
    total_count = (
        await db.execute(select(func.count()).select_from(filtered.subquery()))
    ).scalar_one()
    rows = (
        await db.execute(
            filtered.order_by(SystemLog.created_at.desc())
            .offset(pagination["offset"])
            .limit(pagination["page_size"])
        )
    ).scalars().all()
    return PaginatedResponse(
        data=[SystemLogRead.model_validate(row) for row in rows],
        pagination=build_pagination_meta(
            page=pagination["page"],
            page_size=pagination["page_size"],
            offset=pagination["offset"],
            total_count=total_count,
        ),
    )


@router.get("/export")
async def export_system_logs(
    current_user: CurrentUser,
    db: DbSession,
    log_name: Annotated[str | None, Query()] = None,
    logging_level: Annotated[str | None, Query()] = None,
) -> StreamingResponse:
    _require_maintenance_reader(current_user)
    rows = (
        await db.execute(
            _filtered_stmt(log_name=log_name, logging_level=logging_level).order_by(
                SystemLog.created_at.desc()
            )
        )
    ).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_COLUMNS)
    for row in rows:
        writer.writerow(
            [
                row.created_at,
                row.log_name,
                row.logging_level,
                row.recon_name,
                row.username,
                row.user_email,
                row.event_stage,
                row.log_message,
                row.request_url,
                row.request_id,
                row.time_taken,
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="Logs_export.csv"'},
    )
