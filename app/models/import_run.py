"""Run Import — one `ImportRun` per uploaded file, and the rows it
produced in `ImportedRow`.

**A deliberate departure from the old backend, not a port.** The old
`run_import` app stores imported data in a Postgres object created
*dynamically per recon* (`recon_data.vw_app_<recon_id>`, built via a
live `ALTER TABLE`/`create_table` call whenever a dimension is added —
confirmed via `recon_data.f_fetch_data` in the old backend's own
`query.sql`), with one physical column per dimension. That's exactly
the anti-pattern `architecture.md` §1/§2 is written against: schema
that only exists as live DDL, invisible outside a `psql` session, and
that can't be partitioned or bulk-queried across recons. `architecture.
md` §2 recommends the alternative directly: *"audit/event history...
is a better fit for Postgres JSONB columns on a partitioned, insert-
only table."* `ImportedRow.data` (JSONB, keyed by dimension name) is
that — one physical schema for every recon's imported data, queryable
and indexable normally, no DDL at import time.

Not yet physically partitioned by `recon_id` — a real Postgres
`PARTITION BY` migration is a bigger step than this phase needs before
there's real multi-recon data volume to justify it; `(recon_id,
app_number)` is indexed instead, and partitioning is a documented
follow-up (see KT_PHASE5.md), not a silently-dropped requirement.
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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User


class ImportStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    app_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status"), nullable=False, default=ImportStatus.PENDING
    )
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
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

    __table_args__ = (
        CheckConstraint("app_number BETWEEN 1 AND 5", name="ck_import_run_app_number_range"),
        Index("ix_import_runs_recon_id", "recon_id"),
    )


class ImportedRow(Base):
    """One row from an import run. `data` is a JSON object keyed by
    dimension name — every dimension configured for this recon/app,
    whether its value came from the file (`in_file`) or a configured
    default (`top_member`/`default_value`), so a downstream consumer
    (Bridge Members, Transformation) always sees a complete row."""

    __tablename__ = "imported_rows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    import_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("import_runs.id", ondelete="CASCADE"), nullable=False
    )
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    app_number: Mapped[int] = mapped_column(Integer, nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    kickout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_imported_rows_recon_app", "recon_id", "app_number"),
        Index("ix_imported_rows_import_run_id", "import_run_id"),
    )
