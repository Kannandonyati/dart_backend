"""Lob / Team / Group, Role/Privilege, and Membership.

The explicit, testable replacement for `f_validate_access`'s PL/pgSQL
join (docs/BUILD_PLAN.md §4) — a join across
`recon_admin.vw_usr_rcn_grp_details` / `vw_usr_type_access` that was
unreadable, untestable, and silently denied every user when a recon had
zero group links (the root cause of a bug fixed earlier this project).

`Membership` is deliberately one polymorphic table (user + scope_type +
scope_id + role) instead of the old backend's six near-identical M2M
tables (group_admin, group_member, team_admin, team_member, lob_admin,
lob_member) — one well-indexed table and one code path to test, instead
of six. `role_id` is nullable: a row with no role is "this user belongs
to this scope" (the old backend's plain `group_member`/`lob_member`
concept); a row with a role is "this user holds this role in this
scope" — same table, same code path, both Phase 1's original meaning
and Phase 3's addition.

**Group is many-to-many with both Lob and Team, not single-parent.**
Phase 1 originally modeled `Group.team_id` as a required single FK —
wrong, caught during Phase 3 by checking the old backend's actual
`create_group`/`add/lob_grp`/`add/team_grp` endpoints and the existing
frontend's `GroupDetails.lobNames`/`teamNames` (both arrays): a group is
created standalone (name only) and linked to zero or more Lobs and zero
or more Teams afterward via separate calls. `group_lobs`/`group_teams`
below replace the old single FK.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.global_variable import group_global_variables

if TYPE_CHECKING:
    from app.models.global_variable import GlobalVariable
    from app.models.user import User


class ScopeType(enum.StrEnum):
    LOB = "lob"
    TEAM = "team"
    GROUP = "group"


class Lob(Base):
    """ "Department" in the frontend's Manage Recon Security page."""

    __tablename__ = "lobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    teams: Mapped[list["Team"]] = relationship(back_populates="lob", cascade="all, delete-orphan")
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])


class Team(Base):
    """Still single-parented to exactly one Lob — confirmed against the
    old backend's `create_team` (`lob_name` required and checked in the
    success path), unlike Group below."""

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    lob_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lobs.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lob: Mapped["Lob"] = relationship(back_populates="teams")

    __table_args__ = (UniqueConstraint("lob_id", "name", name="uq_team_lob_name"),)


group_lobs = Table(
    "group_lobs",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "lob_id", UUID(as_uuid=True), ForeignKey("lobs.id", ondelete="CASCADE"), primary_key=True
    ),
)

group_teams = Table(
    "group_teams",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "team_id", UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    ),
)

group_roles = Table(
    "group_roles",
    Base.metadata,
    Column(
        "group_id",
        UUID(as_uuid=True),
        ForeignKey("groups.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    ),
)


class Group(Base):
    """Standalone entity — NOT parented to a Team (see module docstring).
    Linked to Lobs/Teams/Roles via the M2M tables above, and to Recons via
    `recon_group_xref` (app/models/recon.py)."""

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id])
    lobs: Mapped[list["Lob"]] = relationship(secondary=group_lobs)
    teams: Mapped[list["Team"]] = relationship(secondary=group_teams)
    roles: Mapped[list["Role"]] = relationship(secondary=group_roles, back_populates="groups")
    global_variables: Mapped[list["GlobalVariable"]] = relationship(
        secondary=group_global_variables, back_populates="groups"
    )


role_privileges = Table(
    "role_privileges",
    Base.metadata,
    Column(
        "role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    ),
    Column(
        "privilege_id",
        UUID(as_uuid=True),
        ForeignKey("privileges.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Privilege(Base):
    """A fine-grained permission string, e.g. "user:manage". Confirmed
    real privilege names from the old backend (traced live via
    f_validate_access this project): delete_recon, update_recon,
    access_recon — Phase 2+ endpoints will seed those; Phase 1 seeds
    only what its own endpoints (user management) actually check."""

    __tablename__ = "privileges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    roles: Mapped[list["Role"]] = relationship(
        secondary=role_privileges, back_populates="privileges"
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    privileges: Mapped[list["Privilege"]] = relationship(
        secondary=role_privileges, back_populates="roles"
    )
    memberships: Mapped[list["Membership"]] = relationship(back_populates="role")
    groups: Mapped[list["Group"]] = relationship(secondary=group_roles, back_populates="roles")


class Membership(Base):
    """One row = "this user belongs to this scope," optionally "...and
    holds this role there." `role_id` is nullable on purpose (added
    Phase 3): a NULL-role row is the old backend's plain
    `group_member`/`lob_member` concept (belongs, no privilege
    implied); a row with a role is Phase 1's original meaning (belongs
    *and* holds a role there). `user_has_privilege` (app/core/
    permissions.py) joins through `role_id`, so a NULL-role row
    correctly grants no privilege on its own — exactly right, no change
    needed there.

    Scope inheritance (a Team-level role implying access to every Group
    under it) is intentionally NOT implemented — every check is an exact
    scope match. Nor does a Role linked to a Group via `group_roles`
    (Phase 3) automatically flow into this table's privilege checks for
    that group's members — that's real old-backend behavior
    (`f_validate_access` computed it that way) but deliberately deferred
    here rather than guessed at; see KT_PHASE3.md's "Known gaps."
    Extend `user_has_privilege` when a real consumer needs either."""

    __tablename__ = "memberships"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    scope_type: Mapped[ScopeType] = mapped_column(
        Enum(ScopeType, name="scope_type"), nullable=False
    )
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="memberships")
    role: Mapped["Role | None"] = relationship(back_populates="memberships")

    __table_args__ = (
        # Covers every role-bearing row (a user can hold a given role in a
        # given scope only once). Postgres treats NULL as distinct from
        # NULL, so this does NOT stop duplicate plain-member rows — the
        # partial index below covers that separately.
        UniqueConstraint("user_id", "scope_type", "scope_id", "role_id", name="uq_membership"),
        Index(
            "uq_membership_plain",
            "user_id",
            "scope_type",
            "scope_id",
            unique=True,
            postgresql_where=text("role_id IS NULL"),
        ),
    )
