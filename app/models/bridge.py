"""Bridge Members — the crosswalk that normalizes each app's raw
dimension values to a common canonical name before cross-system
matching, plus `BridgeRun`, the long-running computation that applies
it across a recon's imported data.

Confirmed against the old backend's `bridge_members` app: a "bridge
member" is NOT a matched pair of rows — it's a mapping entry keyed by
`(recon, app_number, dimension_name, source_member)` to a canonical
`bridge_member` value (e.g. two apps' different account-code schemes
both mapping to the same canonical account name). `AMOUNT` is excluded
by the old backend on purpose ("Measure role... is not a bridge member
dimension" — it's the value being reconciled, not a matching key) and
excluded here the same way. A mapping's `bridge_member` value of the
literal string `"kickout"` (case-insensitive) is the old backend's own
sentinel for "this source value has no real mapping yet" — kept as the
same sentinel here rather than inventing a different one, since
`BridgeMapping.bridge_member` is free text either way and a boolean
"is this a kickout mapping" column would just be redundant with it.

`BridgeRun` mirrors `ImportRun`'s shape (Phase 5) — same status
lifecycle, same "Celery task tracked by a status/progress row" pattern
— run against the already-imported `ImportedRow`s for a recon, not a
new file upload.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User

KICKOUT_SENTINEL = "kickout"


class BridgeMapping(Base):
    __tablename__ = "bridge_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    app_number: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_member: Mapped[str] = mapped_column(String(500), nullable=False)
    bridge_member: Mapped[str] = mapped_column(String(500), nullable=False)
    flip_sign: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dim_comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    bridge_comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    je_comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    is_invalid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "recon_id",
            "app_number",
            "dimension_name",
            "source_member",
            name="uq_bridge_mapping_key",
        ),
        CheckConstraint("app_number BETWEEN 1 AND 5", name="ck_bridge_mapping_app_number_range"),
        Index("ix_bridge_mappings_recon_app", "recon_id", "app_number"),
    )


class BridgeRunStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class BridgeRun(Base):
    __tablename__ = "bridge_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[BridgeRunStatus] = mapped_column(
        Enum(BridgeRunStatus, name="bridge_run_status"),
        nullable=False,
        default=BridgeRunStatus.PENDING,
    )
    total_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kickout_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped["User"] = relationship()

    __table_args__ = (Index("ix_bridge_runs_recon_id", "recon_id"),)
