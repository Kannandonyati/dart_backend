"""Account-wide audit-mode history — old Dart audit_history."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditMode(Base):
    __tablename__ = "audit_modes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    admin_name: Mapped[str] = mapped_column(String(150), nullable=False)
    audit_status: Mapped[bool] = mapped_column(Boolean, nullable=False)
    start_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
