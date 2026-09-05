"""User model — Phase 1 identity core.

Replaces the old backend's login path (docs/BUILD_PLAN.md §4), which
hashed every password with a single hardcoded salt
(`make_password(password, salt='dart')`) and did the comparison inside
the unreadable stored procedure. Here, hashing is Argon2 with a real
per-user random salt (app.core.security), and verification is plain,
testable Python in app/api/v1/endpoints/auth.py.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.security import Membership

USER_TYPE_VALUES = (
    "Account Admin",
    "Group Owner",
    "Department Admin",
    "Recon User",
    "Team Admin",
)
"""The old backend's actual, closed user-type vocabulary — confirmed
against `recon_admin.user_admins` (account_admin/lob_admin/team_admin/
group_owner booleans) and `recon_admin.user_members` (recon_user
boolean) in the reference database (Data_Recon_Database, Multiapp_Karan
branch), and against the live reference system's own Manage Users
screen, which shows exactly these five labels. "Department Admin" is
the UI label for the DB's `lob_admin` flag — same relationship as
Phase 1's dimension/LOB naming elsewhere in this codebase.

Deliberately a flat array on `User`, NOT modeled through Phase 3's
Membership(user, scope_type, scope_id, role) — that system scopes a
role to a *specific* group/team/lob instance (a genuinely more capable
model), which is real and correct for "Manage Recon Security", but this
column exists to faithfully reproduce old DART's own Manage Users page,
which shows and edits exactly these five flat, unscoped flags with no
"which group" dimension at all. Unifying the two is future work, not
solved here on a guess — see KT notes for this decision."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """Soft delete — replaces an earlier "Deactivate" design (is_active
    alone) that kept a removed user visibly listed with a "Deactivated"
    badge. The reference system's Manage Users screen has no such
    concept: its trash-can action removes the row from the list outright
    (confirmed against the reference database's `dart_user.end_date`, a
    temporal column — every "current" view there filters `end_date IS
    NULL`, so an end-dated user simply isn't in any list anymore, same
    as this column's effect on GET /users and GET /users/invited).

    A real hard DELETE isn't possible here regardless: `Recon.owner_id`
    is `ondelete="RESTRICT"`, so deleting a user who owns a recon would
    just fail. Soft-delete is the correct choice on this schema, not
    only a faithful copy of the reference system's own effective
    behavior — same "soft delete, not hard" precedent as `Recon.deleted_at`
    (Phase 2)."""
    invite_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """NULL means "created via invite, invite not yet redeemed" — the ONLY
    case that produces NULL. A user created directly (`POST /users`, the
    seed script's bootstrap/default accounts, or any pre-existing row) gets
    this set at creation time, since there's no invite step for them to
    complete. Exists to fix a real bug found while wiring the frontend's
    Manage Users page to this backend: `is_active=False` alone can't
    distinguish "never accepted their invite" from "was active, later
    deactivated" — both set the same boolean. `GET /users/invited` (Phase 9)
    now filters on this column instead."""
    # Break-glass bootstrap flag: bypasses require_privilege entirely
    # (see app/core/permissions.py). Reserved for the seeded bootstrap
    # account — real users should get privileges through Membership
    # once Phase 3's group-management endpoints exist, not this flag.
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    """The tier above `is_superuser` — the only one that can change which
    UI components the rest of the application is allowed to show (see
    app/core/ui_components.py).

    A separate flag rather than reusing `is_superuser` because that one
    isn't exclusive: `sync_user_type_grants` sets it on *every* user
    given the "Account Admin" user type, so an Account Admin could
    otherwise switch navigation off for the whole tenant, including for
    the people who granted them the type. Nothing in the user-facing API
    can set this column — not `POST /users`, not
    `PATCH /users/{id}/user-types` (a different field entirely), and not
    the invite flow. It is set by app/db/seed.py alone, so the tier can
    only be conferred by someone with server access.

    Implies every privilege (permissions.py short-circuits on it) and is
    always exempt from component visibility, so a platform admin cannot
    hide their own way back into the admin console."""
    user_types: Mapped[list[str]] = mapped_column(
        ARRAY(String), nullable=False, default=list, server_default="{}"
    )
    """Manage Users' "User Type" column. Synced to real grants by
    `sync_user_type_grants` (Account Admin → is_superuser; Group Owner /
    Department Admin / Team Admin → security:manage; Recon User →
    group-linked recon access). Still a flat, unscoped vocabulary — scoped
    memberships stay on Manage Recon Security."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    memberships: Mapped[list["Membership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
