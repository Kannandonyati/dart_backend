"""Authorization: the explicit, testable replacement for `f_validate_access`.

Old model (docs/BUILD_PLAN.md §4): a PL/pgSQL join across
`recon_admin.vw_usr_rcn_grp_details` / `vw_usr_type_access`, unreadable,
untestable, and confirmed (this project, earlier phase) to silently deny
every user when the target row had zero group links, with no error
explaining why. New model: one indexed query against
Membership → Role → Privilege, in plain Python, with a unit test for
every case that query needs to handle — see tests/test_permissions.py.

Usage:

    @router.post("/users", dependencies=[require_privilege("user:manage")])
    async def create_user(...): ...

`current_user.is_superuser` bypasses this entirely — see the note on
that flag in app/models/user.py for what it's for and isn't for.
"""

from typing import cast
from uuid import UUID

from fastapi import Depends
from fastapi.params import Depends as DependsMarker
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import PermissionDeniedError
from app.core.scope_access import accessible_group_ids
from app.models.security import Membership, Privilege, Role, group_roles, role_privileges


async def user_has_privilege(db: DbSession, user_id: UUID, privilege_name: str) -> bool:
    stmt = (
        select(Membership.id)
        .join(Role, Role.id == Membership.role_id)
        .join(role_privileges, role_privileges.c.role_id == Role.id)
        .join(Privilege, Privilege.id == role_privileges.c.privilege_id)
        .where(Membership.user_id == user_id, Privilege.name == privilege_name)
        .limit(1)
    )
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        return True

    group_ids = await accessible_group_ids(db, user_id)
    if not group_ids:
        return False
    via_group = (
        select(group_roles.c.role_id)
        .join(role_privileges, role_privileges.c.role_id == group_roles.c.role_id)
        .join(Privilege, Privilege.id == role_privileges.c.privilege_id)
        .where(group_roles.c.group_id.in_(group_ids), Privilege.name == privilege_name)
        .limit(1)
    )
    return (await db.execute(via_group)).scalar_one_or_none() is not None


def require_privilege(privilege_name: str) -> DependsMarker:
    """Returns a FastAPI dependency suitable for a route's `dependencies=`
    list. Raises PermissionDeniedError (403) if the current user has
    neither a bypass flag (`is_platform_admin` / `is_superuser`) nor a
    Membership granting this privilege in any scope."""

    async def _check(current_user: CurrentUser, db: DbSession) -> None:
        if current_user.is_platform_admin or current_user.is_superuser:
            return
        if not await user_has_privilege(db, current_user.id, privilege_name):
            raise PermissionDeniedError(
                f"Missing required privilege: {privilege_name}", code="permission_denied"
            )

    return cast(DependsMarker, Depends(_check))
