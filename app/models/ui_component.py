"""Stored decisions about UI component visibility.

Only *overrides* live here — the catalog of what can be toggled is in
app/core/ui_components.py, and everything is visible unless a row here
says otherwise. So an empty table means "stock application", which is
both the correct initial state and a trivial reset: delete the row.

`audience` is what makes this more than a global kill switch. A row with
audience `everyone` is the baseline; a row naming a single user type
overrides that baseline for exactly those users. That covers the case a
plain boolean can't — hiding Workflow Automation from Recon Users while
Account Admins keep it — without needing a row per user.

Not modeled through Phase 3's Membership/Role/Privilege system on
purpose. That system answers "may this user perform this action", scoped
to a specific group or team instance. This one answers "should this
chrome render", which is a tenant-wide presentation decision with no
scope dimension at all. Overloading privileges to carry it would mean
inventing a privilege per tab and granting them through group
memberships, which is both a worse fit and a far bigger blast radius.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User

EVERYONE_AUDIENCE = "everyone"
"""The baseline audience. Stored as a sentinel string rather than NULL so
the unique constraint on (component_key, audience) actually catches
duplicates — in Postgres, NULLs don't collide, so a nullable column
would happily accept two conflicting baseline rows."""


class UiComponentSetting(Base):
    __tablename__ = "ui_component_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    component_key: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    """A key from app/core/ui_components.py. Not a foreign key — the
    catalog is code, not a table. Rows whose key is no longer in the
    catalog are ignored by the resolver rather than deleted, so rolling
    the frontend back doesn't discard an operator's decision."""
    audience: Mapped[str] = mapped_column(
        String(50), nullable=False, default=EVERYONE_AUDIENCE, server_default=EVERYONE_AUDIENCE
    )
    """`everyone`, or one value from app/models/user.py's
    USER_TYPE_VALUES."""
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    """Who last changed it. `SET NULL` rather than RESTRICT: deleting the
    admin who flipped a switch must not be blocked by, or silently undo,
    that switch."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    updated_by: Mapped["User | None"] = relationship(
        foreign_keys=[updated_by_user_id], lazy="raise"
    )
    """`lazy="raise"` so a missing eager-load surfaces as a loud error
    here rather than an async lazy-load failure deep inside response
    serialization — the console's list endpoint selectinloads it."""

    __table_args__ = (
        UniqueConstraint("component_key", "audience", name="uq_ui_component_audience"),
    )
