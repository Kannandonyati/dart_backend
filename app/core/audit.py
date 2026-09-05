"""Shared audit-log recording helper.

Deliberately does NOT call `db.commit()` — it stages the insert on the
caller's existing session, and rides along with whatever commit the
calling endpoint was already about to do. This keeps recording an audit
entry a zero-extra-round-trip addition rather than a second transaction,
and means an audit row is never persisted for a mutation that itself
failed to commit.
"""

import uuid

from app.api.deps import DbSession
from app.core.request_context import get_request_path
from app.models.audit import AuditLog


async def record_audit_log(
    db: DbSession,
    *,
    actor_user_id: uuid.UUID | None,
    action: str,
    recon_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    detail: dict[str, str] | None = None,
) -> None:
    recorded = dict(detail) if detail else {}
    request_url = get_request_path()
    if request_url and "request_url" not in recorded:
        recorded["request_url"] = request_url
    db.add(
        AuditLog(
            actor_user_id=actor_user_id,
            recon_id=recon_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            detail=recorded or None,
        )
    )
