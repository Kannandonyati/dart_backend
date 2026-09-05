"""Audit Log reads — replaces the old backend's `Logentries` app.

Three views, each scoped differently on purpose (see app/models/audit.py's
module docstring for the access-control gap this deliberately closes
relative to the old backend):

- `GET /audit-logs` — every recon's trail, `is_superuser` only.
- `GET /audit-logs/mine` — the caller's own actions across every recon
  they've touched, any authenticated user (replaces old `user_logs`,
  which was already scoped by acting user).
- `GET /recons/{recon_id}/audit-logs` — one recon's trail, anyone who
  can already manage that recon (owner, `recon:manage_all`, or
  superuser) — deliberately not gated by whether the recon is still
  active, since a deleted recon's own delete event is exactly the kind
  of thing this view exists to show (see the endpoint's own comment).

Route order: `/audit-logs/mine`, `/audit-logs/users`, and
`/audit-logs/export` are literal segments on the top-level router;
there is no `/audit-logs/{id}` route to conflict with them.
"""

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.exceptions import NotFoundError, PermissionDeniedError
from app.core.permissions import require_privilege
from app.core.recon_access import can_manage_recon
from app.models.audit import AuditLog
from app.models.recon import Recon
from app.models.user import User
from app.schemas.audit import AuditLogRead
from app.schemas.pagination import PaginatedResponse, build_pagination_meta

# Every list endpoint below joins in the acting user's username and the
# recon's name at read time (AuditLog only stores the raw ids) so the
# frontend's User Logs table can show human-readable "User" and "Recon
# Name" columns matching old DART's Logentries output, instead of raw
# UUIDs or "—".


def _to_read(row: tuple[AuditLog, str | None, str | None]) -> AuditLogRead:
    log, actor_username, recon_name = row
    return AuditLogRead(
        id=log.id,
        actor_user_id=log.actor_user_id,
        actor_username=actor_username,
        recon_id=log.recon_id,
        recon_name=recon_name,
        action=log.action,
        entity_type=log.entity_type,
        entity_id=log.entity_id,
        detail=log.detail,
        created_at=log.created_at,
    )


router = APIRouter(tags=["audit-logs"])
recon_router = APIRouter(prefix="/recons/{recon_id}/audit-logs", tags=["audit-logs"])


def _require_superuser(current_user: CurrentUser) -> None:
    if not current_user.is_superuser:
        raise PermissionDeniedError("Only a superuser may view the system-wide audit trail.")


@router.get("/audit-logs", response_model=list[AuditLogRead])
async def list_all_audit_logs(
    current_user: CurrentUser,
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[AuditLogRead]:
    _require_superuser(current_user)
    stmt = (
        select(AuditLog, User.username, Recon.name)
        .outerjoin(User, AuditLog.actor_user_id == User.id)
        .outerjoin(Recon, AuditLog.recon_id == Recon.id)
        .order_by(AuditLog.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    return [_to_read(row) for row in (await db.execute(stmt)).all()]


@router.get(
    "/audit-logs/users",
    response_model=PaginatedResponse[AuditLogRead],
    dependencies=[require_privilege("user:manage")],
)
async def list_users_audit_logs(
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> PaginatedResponse[AuditLogRead]:
    """Manage Users' User activity table — every actor, not just the
    caller. Old `logs/user` was system-wide; `/audit-logs/mine` is the
    personal view. Privilege-gated so a plain recon user cannot read
    other people's trail (the old Logentries disclosure we closed)."""
    total_count = (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one()
    stmt = (
        select(AuditLog, User.username, Recon.name)
        .outerjoin(User, AuditLog.actor_user_id == User.id)
        .outerjoin(Recon, AuditLog.recon_id == Recon.id)
        .order_by(AuditLog.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    return PaginatedResponse(
        data=[_to_read(row) for row in (await db.execute(stmt)).all()],
        pagination=build_pagination_meta(
            page=pagination["page"],
            page_size=pagination["page_size"],
            offset=pagination["offset"],
            total_count=total_count,
        ),
    )


@router.get("/audit-logs/mine", response_model=PaginatedResponse[AuditLogRead])
async def list_my_audit_logs(
    current_user: CurrentUser,
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> PaginatedResponse[AuditLogRead]:
    """Manage Users' "User activity" table pager needs a real total_count
    — see app/schemas/pagination.py's module docstring for why this is the
    one audit-log view (of the three read views in this module) that
    returns the `{data, pagination}` envelope instead of a bare array; the
    other two (`/audit-logs`, `/recons/{id}/audit-logs`) have no current
    frontend consumer that renders a total, so they're left unchanged."""
    total_count = (
        await db.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.actor_user_id == current_user.id)
        )
    ).scalar_one()
    stmt = (
        select(AuditLog, User.username, Recon.name)
        .outerjoin(User, AuditLog.actor_user_id == User.id)
        .outerjoin(Recon, AuditLog.recon_id == Recon.id)
        .where(AuditLog.actor_user_id == current_user.id)
        .order_by(AuditLog.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    return PaginatedResponse(
        data=[_to_read(row) for row in (await db.execute(stmt)).all()],
        pagination=build_pagination_meta(
            page=pagination["page"],
            page_size=pagination["page_size"],
            offset=pagination["offset"],
            total_count=total_count,
        ),
    )


@router.get("/audit-logs/export")
async def export_all_audit_logs(current_user: CurrentUser, db: DbSession) -> StreamingResponse:
    _require_superuser(current_user)
    stmt = (
        select(AuditLog, User.username, Recon.name)
        .outerjoin(User, AuditLog.actor_user_id == User.id)
        .outerjoin(Recon, AuditLog.recon_id == Recon.id)
        .order_by(AuditLog.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["created_at", "user", "recon_name", "action", "entity_type", "entity_id", "detail"]
    )
    for log, username, recon_name in rows:
        writer.writerow(
            [log.created_at, username, recon_name, log.action, log.entity_type,
             log.entity_id, log.detail]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_logs.csv"'},
    )


@recon_router.get("", response_model=list[AuditLogRead])
async def list_recon_audit_logs(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[AuditLogRead]:
    # Deliberately NOT `get_accessible_recon` — that excludes soft-deleted
    # recons (Recon.deleted_at IS NOT NULL), which would make a recon's
    # own delete event (and everything before it) permanently
    # unreviewable the moment it's deleted. An audit trail's whole point
    # is surviving the thing it's a trail of, so this loads the recon
    # regardless of deletion state and applies the same ownership check
    # `get_accessible_recon` would, without the extra filter.
    recon = await db.get(Recon, recon_id)
    if recon is None or not await can_manage_recon(db, current_user, recon):
        raise NotFoundError("Recon not found")
    stmt = (
        select(AuditLog, User.username, Recon.name)
        .outerjoin(User, AuditLog.actor_user_id == User.id)
        .outerjoin(Recon, AuditLog.recon_id == Recon.id)
        .where(AuditLog.recon_id == recon_id)
        .order_by(AuditLog.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    return [_to_read(row) for row in (await db.execute(stmt)).all()]
