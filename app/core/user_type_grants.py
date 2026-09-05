"""Map Manage Users' flat user-type labels onto real privileges.

Old DART wrote these flags into `user_admins` / `user_members` and
`f_validate_access` read them. This rebuild stored the same five labels
on `User.user_types` but only synced Account Admin → `is_superuser`.
The other four were display-only — editing them on Manage Users did
nothing. This module is the missing write-side: after a type change,
grant or revoke the matching Membership → Role → Privilege rows.

The grant is unscoped (a sentinel group id) on purpose — old Manage
Users had no "which group" dimension either. Scoped memberships on a
real LOB/Team/Group stay on Manage Recon Security.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models.security import Membership, Privilege, Role, ScopeType
from app.models.user import User

SECURITY_USER_TYPES = frozenset({"Group Owner", "Department Admin", "Team Admin"})
RECON_USER_TYPE = "Recon User"

_SECURITY_ROLE_NAME = "_user_type:security"
_RECON_ROLE_NAME = "_user_type:recon"
# Not a real group — user_has_privilege ignores scope. Kept out of
# recon_group_xref so it can never accidentally open a recon.
_TYPE_GRANT_SCOPE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


async def sync_user_type_grants(db: DbSession, user: User) -> None:
    """Idempotent: make the user's type-grant memberships match
    `user.user_types`. Caller owns the commit."""
    user.is_superuser = "Account Admin" in user.user_types
    await _sync_named_grant(
        db,
        user,
        role_name=_SECURITY_ROLE_NAME,
        privilege_names=("security:manage",),
        should_have=bool(SECURITY_USER_TYPES & set(user.user_types)),
    )
    await _sync_named_grant(
        db,
        user,
        role_name=_RECON_ROLE_NAME,
        privilege_names=("execute_recon", "read_recon"),
        should_have=RECON_USER_TYPE in user.user_types,
    )


async def _sync_named_grant(
    db: DbSession,
    user: User,
    *,
    role_name: str,
    privilege_names: tuple[str, ...],
    should_have: bool,
) -> None:
    role = await _get_or_create_role(db, role_name, privilege_names)
    existing = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.role_id == role.id,
                Membership.scope_type == ScopeType.GROUP,
                Membership.scope_id == _TYPE_GRANT_SCOPE_ID,
            )
        )
    ).scalar_one_or_none()

    if should_have and existing is None:
        db.add(
            Membership(
                user_id=user.id,
                scope_type=ScopeType.GROUP,
                scope_id=_TYPE_GRANT_SCOPE_ID,
                role_id=role.id,
            )
        )
    elif not should_have and existing is not None:
        await db.delete(existing)


async def _get_or_create_role(
    db: DbSession, role_name: str, privilege_names: tuple[str, ...]
) -> Role:
    role = (
        await db.execute(
            select(Role).options(selectinload(Role.privileges)).where(Role.name == role_name)
        )
    ).scalar_one_or_none()
    if role is None:
        role = Role(name=role_name, privileges=[])
        db.add(role)
        await db.flush()

    have = {p.name for p in role.privileges}
    for name in privilege_names:
        if name in have:
            continue
        privilege = (await db.execute(select(Privilege).where(Privilege.name == name))).scalar_one_or_none()
        if privilege is None:
            privilege = Privilege(name=name)
            db.add(privilege)
            await db.flush()
        role.privileges.append(privilege)
    await db.flush()
    return role
