"""Run Report — sign-off state and saved report filters.

Confirmed against the old backend's `run_report` app (`rcn_signoff.py`,
`run_rprt.py`, `rpt_filter_list.py`): the *computation* itself
(`create_report`/`fetch_data`) is entirely opaque, living inside a
stored procedure (`sp_master`) this repository never exposes as
readable Python — the same situation Phase 5/6 found for import parsing
and bridge CSV import, resolved the same way: define the contract here,
document it as a decision, don't guess at hidden SQL.

Two things ARE readable and are ported faithfully:

- **Sign-off is a per-(recon, app) boolean**, not a per-row or per-recon
  flag — confirmed by `rcn_signoff.py` calling `modify_recon_signoff`
  once per `app_type` in the request's `app_type` list.
- **Report filters are named, saved, per-recon criteria** users apply to
  narrow the report and see a second ("filtered") variance figure next
  to the unfiltered ("original") one — confirmed by `run_rprt.py`'s own
  merge of `all_report_original`/`all_report_filtered` and the
  `import_filter`/`update_filter`/`filter_list`/`filter_mem_list`
  endpoint surface in `run_report/urls.py`.

The report computation's actual row/variance shape is new-backend-
defined — see `app/api/v1/endpoints/report_data.py`'s module docstring
for the full design decision.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReportSignoff(Base):
    __tablename__ = "report_signoffs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    app_number: Mapped[int] = mapped_column(Integer, nullable=False)
    signed_off: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    signed_off_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    signed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("recon_id", "app_number", name="uq_report_signoff_recon_app"),
        CheckConstraint("app_number BETWEEN 1 AND 5", name="ck_report_signoff_app_number_range"),
    )


class ReportFilter(Base):
    """A saved, named filter: `criteria` maps dimension name to the set
    of member values to include (an IN filter), applied against
    `ImportedRow.data` at report-run time — same "computed at read time,
    not persisted" precedent as Bridge/Sync's resolved values."""

    __tablename__ = "report_filters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    criteria: Mapped[dict[str, list[str]]] = mapped_column(JSONB, nullable=False)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("recon_id", "name", name="uq_report_filter_recon_name"),)
