"""Named Global Variables and the groups they are linked to.

Old Dart stored `group_details.gv_name` and linked via add/grp_recon
with `globalvar_name`. This rebuild keeps a small catalog plus a
group↔name junction so Manage Security can attach GVs without a
pipeline GV runtime.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Table, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

group_global_variables = Table(
    "group_global_variables",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "global_variable_id",
        UUID(as_uuid=True),
        ForeignKey("global_variables.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class GlobalVariable(Base):
    __tablename__ = "global_variables"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    groups: Mapped[list["Group"]] = relationship(  # noqa: F821
        secondary=group_global_variables, back_populates="global_variables"
    )
