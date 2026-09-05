"""Recon — Phase 2 core.

Replaces the old backend's `Select` app (docs/BUILD_PLAN.md §2, §6
Phase 2). Two deliberate simplifications, documented rather than
guessed at:

- **Soft delete, not hard delete.** The old frontend's "Delete" button
  actually calls `modify_recon` with `is_deleted:true` (a soft flag) —
  not the separate `drop_recon` hard-delete path, which this session
  confirmed is broken and unused. `deleted_at` replicates that: a
  deleted recon is filtered out of every list/get, never physically
  removed (preserves the audit trail once Phase 9 exists, and avoids
  cascade-delete complexity with dimension/bridge/transformation/report
  child data once Phases 4-8 add them).
- **Ownership is the access model for now, not group membership.**
  Phase 3 (group management + group↔recon linking endpoints) doesn't
  exist yet, so scoping recon access to "which group is this recon
  linked to" would be unusable — nothing can create that link yet. A
  recon's owner can always read/update/delete it; `recon:manage_all`
  (see app/core/permissions.py usage in recons.py) is the escape hatch
  for admins acting on recons they don't own. Group-based access
  (`recon_group_xref`, defined here) is wired into the *read* path
  (list-available) now so it's ready the moment Phase 3 lands, but nothing
  can populate it yet.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, Table, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.security import Group
    from app.models.user import User

recon_group_xref = Table(
    "recon_group_xref",
    Base.metadata,
    Column(
        "recon_id",
        UUID(as_uuid=True),
        ForeignKey("recons.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Recon(Base):
    __tablename__ = "recons"
    __table_args__ = (
        # Unique among live recons only. A soft-deleted row must not
        # block recreating the same name — the Select list hides deleted
        # recons, so uniqueness that includes them makes the UI and the
        # API contradict each other.
        Index(
            "uq_recons_name_live",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="Created")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    owner: Mapped["User"] = relationship()
    groups: Mapped[list["Group"]] = relationship(secondary=recon_group_xref)
