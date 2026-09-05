"""Audit Log — a real, queryable, insert-only trail of who did what,
replacing the old backend's `Logentries` app.

Confirmed against the old backend's `Logentries/functions/get_all_logs.py`
and `get_user_logs.py`: a "log" row is `(actor, recon_name, action
detail, created_date)`, populated somewhere inside the same opaque
`sp_master` stored-procedure layer every other phase has found gaps in
— there is no readable Python anywhere that shows what triggers a log
row or what its full shape is. Same resolution as every prior phase:
define a clean contract, wire it into the handful of endpoints where an
audit trail is actually valuable, and document the rest as a known gap
rather than a guess (see KT_PHASE9.md).

**A real access-control gap in the old backend, closed here rather than
replicated.** `Logentries/views.py`'s `all_logs` and `export` endpoints
are decorated only with `@permission_classes((IsAuthenticated,))` — no
privilege check beyond being logged in, meaning any authenticated user
could apparently read every recon's system-wide audit trail. This
backend's `GET /audit-logs` (all-recon view) requires `is_superuser`
instead; any user can still read their own activity (`GET
/audit-logs/mine`) or their own recon's trail (`GET
/recons/{id}/audit-logs`), which covers what the old `user_logs`
endpoint (correctly, only ever queried by-actor) already scoped itself
to.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    recon_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_recon_created", "recon_id", "created_at"),
        Index("ix_audit_logs_actor_created", "actor_user_id", "created_at"),
    )
