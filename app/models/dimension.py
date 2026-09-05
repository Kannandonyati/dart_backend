"""Dimension Linking — per-recon "applications" (source systems being
reconciled) and the dimensions (matching columns) linking them.

A recon is seeded with two apps; Dimension Linking can add more, up to
five (old DART). A recon app is import/parsing settings scoped to one
source system — CSV delimiter, currency formatting, whether the file
has a header row — not a separate business entity. A dimension is one
common name (e.g. `AMOUNT`) shared across apps, with a per-app mapping:
either a column position in that app's file, or (if the value isn't in
the file at all) a fixed default.

Both are hard-deleted, unlike Recon: they're configuration scoped to an
already soft-deletable Recon, not primary records needing their own
audit trail — deleting the parent Recon (`ondelete="CASCADE"`) is the
only real deletion path that matters.

Old-backend seam bridged here the same way Phase 2/3 bridged it for
Recon/Group: every old `dim_linking` endpoint keys by `recon_name`
(string); every new endpoint here is `recon_id`-scoped instead.
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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

MANDATORY_DIMENSION_NAMES = ("YEAR", "PERIOD", "AMOUNT")
"""Confirmed against the old backend's seed_mandatory_dimensions
frontend logic and its own (inconsistently-enforced — see
app/api/v1/endpoints/dimensions.py) bulk-delete exclusion list. Every
recon gets exactly these three, in this order, positions 0-2, and none
of the three can be deleted through this API — a real fix over the old
backend, where only the bulk CSV-import delete path excluded them and
the single-dimension delete endpoint had no such check at all."""


class ReconApp(Base):
    __tablename__ = "recon_apps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    app_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    delimiter: Mapped[str] = mapped_column(String(5), nullable=False, default=",")
    currency_delimiter: Mapped[str | None] = mapped_column(String(5), nullable=True)
    currency_symbol: Mapped[str | None] = mapped_column(String(5), nullable=True)
    thousands_separator: Mapped[str] = mapped_column(String(5), nullable=False, default=",")
    has_header: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("recon_id", "app_number", name="uq_recon_app_number"),
        CheckConstraint("app_number BETWEEN 1 AND 5", name="ck_recon_app_number_range"),
    )


class Dimension(Base):
    __tablename__ = "dimensions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    mappings: Mapped[list["DimensionMapping"]] = relationship(
        back_populates="dimension",
        cascade="all, delete-orphan",
        order_by="DimensionMapping.app_number",
    )

    __table_args__ = (
        UniqueConstraint("recon_id", "name", name="uq_dimension_recon_name"),
        UniqueConstraint("recon_id", "position", name="uq_dimension_recon_position"),
    )


class DimensionMapping(Base):
    """One row per (dimension, app) — how that dimension's value is
    sourced for that specific application's file. `column_location` is
    used when `in_file`; `default_value` is used when not."""

    __tablename__ = "dimension_mappings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dimension_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dimensions.id", ondelete="CASCADE"), nullable=False
    )
    app_number: Mapped[int] = mapped_column(Integer, nullable=False)
    in_file: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    column_location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    default_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    dimension: Mapped["Dimension"] = relationship(back_populates="mappings")

    __table_args__ = (
        UniqueConstraint("dimension_id", "app_number", name="uq_dimension_mapping_app"),
        CheckConstraint("app_number BETWEEN 1 AND 5", name="ck_dimension_mapping_app_number_range"),
    )
