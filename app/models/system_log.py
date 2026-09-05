"""Operational system logs — old Dart Maintenance UNION.

Old Dart had no ORM for this. Writers went to
`recon_audit.log_entries` (userlog / techlog) and
`recon_audit.track_app_data_table` (dblog), then three views were
UNIONed for POST /logs/all_logs. This table is that UNION as one
insert-only model so Maintenance can show real columns instead of
inventing them from `audit_logs`.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

LOG_NAMES = ("userlog", "techlog", "dblog")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    log_name: Mapped[str] = mapped_column(String(20), nullable=False)
    logging_level: Mapped[str] = mapped_column(String(10), nullable=False)
    log_message: Mapped[str] = mapped_column(Text, nullable=False)
    request_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(320), nullable=True)
    username: Mapped[str | None] = mapped_column(String(150), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recon_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    event_stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    time_taken: Mapped[str | None] = mapped_column(String(30), nullable=True)
    variable_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    recon_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_system_logs_created", "created_at"),
        Index("ix_system_logs_log_name_created", "log_name", "created_at"),
        Index("ix_system_logs_level_created", "logging_level", "created_at"),
    )
