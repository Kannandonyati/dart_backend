"""Account-only audit-mode toggle — old Dart POST recon_security/audit_status."""

from datetime import UTC, datetime

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.audit_mode import current_audit_mode
from app.core.permissions import require_privilege
from app.models.audit_mode import AuditMode
from app.schemas.audit_mode import AuditModeRead, AuditModeUpdate

router = APIRouter(prefix="/audit-mode", tags=["security"])
_MANAGE = require_privilege("security:manage")


def _to_read(row: AuditMode | None) -> AuditModeRead:
    if row is None:
        return AuditModeRead(enabled=False)
    return AuditModeRead(enabled=row.audit_status, admin_name=row.admin_name, start_date=row.start_date)


@router.get("", response_model=AuditModeRead)
async def get_audit_mode(db: DbSession) -> AuditModeRead:
    return _to_read(await current_audit_mode(db))


@router.post("", response_model=AuditModeRead, dependencies=[_MANAGE])
async def set_audit_mode(
    body: AuditModeUpdate, current_user: CurrentUser, db: DbSession
) -> AuditModeRead:
    open_row = await current_audit_mode(db)
    if open_row is not None:
        if open_row.audit_status == body.enabled:
            return _to_read(open_row)
        open_row.end_date = datetime.now(UTC)

    row = AuditMode(admin_name=current_user.username, audit_status=body.enabled)
    db.add(row)
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="audit_mode.updated",
        entity_type="audit_mode",
        entity_id=str(row.id),
        detail={"enabled": body.enabled},
    )
    await db.commit()
    await db.refresh(row)
    return _to_read(row)
