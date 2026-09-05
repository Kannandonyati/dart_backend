"""Transformation — a second, separate crosswalk system (the old
backend's "sync map" / `recon_tfn_override`), producing one unified,
synced view across both apps' imported data.

**Confirmed NOT to be cross-app matching/reconciliation.** Phase 6's KT
guessed Transformation would be where App1/App2 rows get paired and
their amounts compared — checking the old backend's actual
`transformation` app directly showed that guess was wrong: its
frontend's row shape is flat, one row per source record (App1 and App2
interleaved, distinguished by `app_name`), not paired rows with two
amounts. No variance/matched-pair entity exists anywhere in the old
backend's readable code. What "transformation" actually is: a second
source→target crosswalk, structurally similar to Phase 6's
`BridgeMapping`, with one real capability Bridge doesn't have —
**multi-dimension concatenation**: several raw dimension values can be
joined into one composite source key (e.g. `ACCOUNT` + `COST_CENTER`)
before mapping to a single `target_sync` value.

**Why this is a separate `SyncMapping`, not an extension of
`BridgeMapping`.** They're structurally near-identical (source→target,
`flip_sign`, soft concepts of deletion) — genuinely tempting to unify,
echoing this project's own Phase 1 precedent of collapsing six
near-identical membership tables into one. Rejected here on purpose:
`BridgeMapping` is already shipped, tested (Phase 6, 121 passing
tests), and load-bearing for kickout detection — retrofitting it with
concat support to serve a different stage's different purpose (final
value synchronization, not match-readiness flagging) would conflate two
concerns for a tangential storage saving. Two clear, single-purpose
tables beat one overloaded one here.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SyncMapping(Base):
    __tablename__ = "sync_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    app_number: Mapped[int] = mapped_column(Integer, nullable=False)
    dimension_names: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    concat_delimiter: Mapped[str] = mapped_column(String(5), nullable=False, default="-")
    source_sync: Mapped[str] = mapped_column(String(1000), nullable=False)
    target_sync: Mapped[str] = mapped_column(String(500), nullable=False)
    flip_sign: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "recon_id", "app_number", "dimension_names", "source_sync", name="uq_sync_mapping_key"
        ),
        CheckConstraint("app_number BETWEEN 1 AND 5", name="ck_sync_mapping_app_number_range"),
        Index("ix_sync_mappings_recon_app", "recon_id", "app_number"),
    )
