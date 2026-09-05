"""Shared recon-ownership access check.

Extracted from app/api/v1/endpoints/recons.py in Phase 4 so pipeline-
stage modules (dimensions.py, and whatever Phase 5+ adds) can enforce
the exact same ownership rule and 404-not-403 behavior recons.py itself
uses, through one shared code path — not a second hand-rolled copy that
could quietly drift (e.g. forget the `recon:manage_all` bypass, or
return 403 instead of 404). Same reasoning as app/api/deps.py's
`load_active_user` being made public in Phase 1 for the same kind of
cross-module reuse.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.core.exceptions import NotFoundError
from app.core.permissions import user_has_privilege
from app.core.scope_access import accessible_group_ids
from app.core.user_type_grants import RECON_USER_TYPE
from app.models.recon import Recon, recon_group_xref
from app.models.user import User


async def can_manage_recon(db: DbSession, user: User, recon: Recon) -> bool:
    if user.is_superuser or recon.owner_id == user.id:
        return True
    if await user_has_privilege(db, user.id, "recon:manage_all"):
        return True
    if RECON_USER_TYPE not in (user.user_types or []):
        return False
    group_ids = await accessible_group_ids(db, user.id)
    if not group_ids:
        return False
    linked = (
        await db.execute(
            select(recon_group_xref.c.group_id)
            .where(
                recon_group_xref.c.recon_id == recon.id,
                recon_group_xref.c.group_id.in_(group_ids),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return linked is not None


async def can_link_recon_group(db: DbSession, user: User, recon: Recon) -> bool:
    """Group linking on Manage Recon Security — security admins can
    attach any recon, not only ones they own."""
    if await can_manage_recon(db, user, recon):
        return True
    return await user_has_privilege(db, user.id, "security:manage")


async def get_accessible_recon(db: DbSession, user: User, recon_id: uuid.UUID) -> Recon:
    """Loads a non-deleted recon and enforces access, or raises
    NotFoundError — never PermissionDeniedError, so a recon that exists
    but isn't yours is indistinguishable from one that doesn't exist at
    all (see recons.py's module docstring for the full enumeration-
    resistance reasoning)."""
    stmt = (
        select(Recon)
        .options(selectinload(Recon.owner), selectinload(Recon.groups))
        .where(Recon.id == recon_id, Recon.deleted_at.is_(None))
    )
    recon = (await db.execute(stmt)).scalar_one_or_none()
    if recon is None or not await can_manage_recon(db, user, recon):
        raise NotFoundError("Recon not found")
    return recon
