"""Recon core — create/list/get/update/delete.

Access model (see app/models/recon.py's docstring for the full
reasoning): any authenticated user can create a recon and always has
full access to ones they own. Acting on a recon you don't own requires
`recon:manage_all` (seeded onto "Account Admin") or `is_superuser`.
Group-based access is wired into `list_available_recons` for when
Phase 3 adds group↔recon linking — it correctly returns nothing until
then, not an error.

Every not-found-or-not-yours case returns 404, never 403 — same
enumeration-resistance reasoning as Phase 1's login endpoint (see
auth.py's docstring): a 403 confirms the recon exists to someone who
otherwise has no way to know that.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.audit import record_audit_log
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import user_has_privilege
from app.core.recon_access import can_link_recon_group, get_accessible_recon
from app.core.recon_bootstrap import seed_new_recon
from app.core.scope_access import accessible_group_ids
from app.models.recon import Recon
from app.models.security import Group
from app.schemas.recon import ReconCreate, ReconRead, ReconUpdate

router = APIRouter(prefix="/recons", tags=["recons"])


def _to_read(recon: Recon) -> ReconRead:
    return ReconRead(
        id=recon.id,
        name=recon.name,
        description=recon.description,
        group_name=recon.groups[0].name if recon.groups else None,
        owner=recon.owner.username,
        status=recon.status,
        archived=recon.archived,
        last_modified=recon.updated_at,
    )


async def _reload(db: DbSession, recon_id: uuid.UUID) -> Recon:
    """Re-fetches a recon with its relationships eager-loaded after a
    write. Deliberately not `db.refresh(recon, attribute_names=[...])`:
    that expires the *whole* instance but only reloads the named
    attributes, leaving anything not listed (e.g. `updated_at`) expired
    — the next access then tries an implicit lazy-load, which fails
    outside an async-safe context. A fresh, fully-eager-loaded SELECT
    has no such partial state to get wrong."""
    stmt = (
        select(Recon)
        .options(selectinload(Recon.owner), selectinload(Recon.groups))
        .where(Recon.id == recon_id)
    )
    recon = (await db.execute(stmt)).scalar_one()
    return recon


_get_owned_or_manageable = get_accessible_recon


async def _get_linkable_recon(db: DbSession, user, recon_id: uuid.UUID) -> Recon:
    stmt = (
        select(Recon)
        .options(selectinload(Recon.owner), selectinload(Recon.groups))
        .where(Recon.id == recon_id, Recon.deleted_at.is_(None))
    )
    recon = (await db.execute(stmt)).scalar_one_or_none()
    if recon is None or not await can_link_recon_group(db, user, recon):
        raise NotFoundError("Recon not found")
    return recon
"""Local alias — kept so every call site below reads the same as before
the Phase 4 extraction of this check (and its `_can_manage` helper) to
app/core/recon_access.py, now shared with dimensions.py."""


async def _live_name_taken(
    db: DbSession, name: str, *, exclude_id: uuid.UUID | None = None
) -> bool:
    stmt = select(Recon.id).where(Recon.name == name, Recon.deleted_at.is_(None))
    if exclude_id is not None:
        stmt = stmt.where(Recon.id != exclude_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


@router.post("", response_model=ReconRead, status_code=201)
async def create_recon(body: ReconCreate, current_user: CurrentUser, db: DbSession) -> ReconRead:
    if await _live_name_taken(db, body.name):
        raise ConflictError("A recon with this name already exists.")

    recon = Recon(name=body.name, description=body.description, owner_id=current_user.id)
    db.add(recon)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Same check-then-insert race as Phase 1's create_user — see that
        # endpoint's comment for why the pre-check alone isn't sufficient.
        await db.rollback()
        raise ConflictError("A recon with this name already exists.") from exc

    # Two application slots and YEAR/PERIOD/AMOUNT, in the same
    # transaction — see app/core/recon_bootstrap.py for what the old
    # backend did here and why this moved.
    await seed_new_recon(db, recon.id)

    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="recon.created",
        recon_id=recon.id,
        entity_type="recon",
        entity_id=str(recon.id),
        detail={"name": recon.name},
    )
    await db.commit()

    recon = await _reload(db, recon.id)
    return _to_read(recon)


@router.get("", response_model=list[ReconRead])
async def list_my_recons(
    current_user: CurrentUser,
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[ReconRead]:
    stmt = (
        select(Recon)
        .options(selectinload(Recon.owner), selectinload(Recon.groups))
        .where(Recon.owner_id == current_user.id, Recon.deleted_at.is_(None))
        .order_by(Recon.updated_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    result = await db.execute(stmt)
    return [_to_read(r) for r in result.scalars().all()]


@router.get("/available", response_model=list[ReconRead])
async def list_available_recons(
    current_user: CurrentUser,
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[ReconRead]:
    """Recons shared via group membership rather than owned outright.
    Structurally correct today, empty in practice: nothing can create a
    recon_group_xref row until Phase 3's group-management endpoints
    exist. Not a bug — see
    tests/test_recons.py::test_list_available_is_empty_until_group_linking_exists."""
    from app.models.security import Group

    member_group_ids = await accessible_group_ids(db, current_user.id)
    if not member_group_ids:
        return []
    stmt = (
        select(Recon)
        .options(selectinload(Recon.owner), selectinload(Recon.groups))
        .where(
            Recon.deleted_at.is_(None),
            Recon.owner_id != current_user.id,
            Recon.groups.any(Group.id.in_(member_group_ids)),
        )
        .order_by(Recon.updated_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    result = await db.execute(stmt)
    return [_to_read(r) for r in result.scalars().all()]


@router.get("/directory", response_model=list[ReconRead])
async def list_recons_for_security(current_user: CurrentUser, db: DbSession) -> list[ReconRead]:
    """Every non-deleted recon name for group-linking dropdowns.
    Superuser / recon:manage_all / security:manage see all; others see
    owned plus group-inherited."""
    stmt = (
        select(Recon)
        .options(selectinload(Recon.owner), selectinload(Recon.groups))
        .where(Recon.deleted_at.is_(None))
        .order_by(Recon.name)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if (
        current_user.is_superuser
        or await user_has_privilege(db, current_user.id, "recon:manage_all")
        or await user_has_privilege(db, current_user.id, "security:manage")
    ):
        return [_to_read(r) for r in rows]
    visible: list[ReconRead] = []
    for recon in rows:
        if await can_link_recon_group(db, current_user, recon):
            visible.append(_to_read(recon))
    return visible


@router.get("/{recon_id}", response_model=ReconRead)
async def get_recon(recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> ReconRead:
    recon = await _get_owned_or_manageable(db, current_user, recon_id)
    return _to_read(recon)


@router.patch("/{recon_id}", response_model=ReconRead)
async def update_recon(
    recon_id: uuid.UUID, body: ReconUpdate, current_user: CurrentUser, db: DbSession
) -> ReconRead:
    recon = await _get_owned_or_manageable(db, current_user, recon_id)

    if body.name is not None and body.name != recon.name:
        if await _live_name_taken(db, body.name, exclude_id=recon.id):
            raise ConflictError("A recon with this name already exists.")
        recon.name = body.name
    if body.description is not None:
        recon.description = body.description

    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A recon with this name already exists.") from exc

    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="recon.updated",
        recon_id=recon.id,
        entity_type="recon",
        entity_id=str(recon.id),
        detail=body.model_dump(exclude_unset=True, exclude_none=True),
    )
    await db.commit()

    recon = await _reload(db, recon.id)
    return _to_read(recon)


@router.delete("/{recon_id}", status_code=204)
async def delete_recon(recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> None:
    recon = await _get_owned_or_manageable(db, current_user, recon_id)
    recon.deleted_at = datetime.now(UTC)
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="recon.deleted",
        recon_id=recon.id,
        entity_type="recon",
        entity_id=str(recon.id),
    )
    await db.commit()


@router.post("/{recon_id}/groups/{group_id}", response_model=ReconRead)
async def link_recon_group(
    recon_id: uuid.UUID, group_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> ReconRead:
    """Old-backend equivalent: add_grp_to_rcn.py, `modify_users_in_recons`
    with `recn_actn: 'a'` — the second half of recon creation there (see
    module docstring). Kept as its own call here too, not folded into
    `create_recon`, for the same two-step shape: the frontend's create
    dialog calls this immediately after create succeeds."""
    recon = await _get_linkable_recon(db, current_user, recon_id)
    group = (await db.execute(select(Group).where(Group.id == group_id))).scalar_one_or_none()
    if group is None:
        raise NotFoundError("Group not found")
    if group not in recon.groups:
        recon.groups.append(group)
        await db.commit()

    recon = await _reload(db, recon.id)
    return _to_read(recon)


@router.delete("/{recon_id}/groups/{group_id}", response_model=ReconRead)
async def unlink_recon_group(
    recon_id: uuid.UUID, group_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> ReconRead:
    recon = await _get_linkable_recon(db, current_user, recon_id)
    recon.groups = [g for g in recon.groups if g.id != group_id]
    await db.commit()

    recon = await _reload(db, recon.id)
    return _to_read(recon)
