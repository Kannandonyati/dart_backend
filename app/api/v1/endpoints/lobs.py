"""LOB ("Department") CRUD plus admin/member management.

Every write here requires the `security:manage` privilege (or
`is_superuser`) — Phase 3 deliberately collapses the old backend's
four-tier (account/lob/team/group) delegated-admin model into one
global privilege, the same simplification Phase 1 made for Membership
(one polymorphic table instead of six) and Phase 2 made for
`recon:manage_all`. Reads are open to any authenticated user — matches
the old backend's read-heavy dropdowns, which were never privilege
gated. See docs/KT_PHASE3.md's "Known gaps" for what this defers.
"""

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import require_privilege
from app.models.security import Lob, Membership, Role, ScopeType
from app.models.user import User
from app.schemas.security import LobCreate, LobRead, LobUpdate, MembershipUserRef

router = APIRouter(prefix="/lobs", tags=["security"])

_MANAGE = require_privilege("security:manage")

ADMIN_ROLE_NAME = "Admin"
"""A row in `role_privileges`-adjacent `memberships` with this role
attached is how "admin of this scope" is represented (see Membership's
docstring in app/models/security.py) — a label, not itself a privilege
grant; `security:manage` is the actual authorization gate. Seeded once
in app/db/seed.py; looked up by name here rather than hardcoding an id."""


async def _get_admin_role_id(db: DbSession) -> uuid.UUID:
    role_id = (
        await db.execute(select(Role.id).where(Role.name == ADMIN_ROLE_NAME))
    ).scalar_one_or_none()
    if role_id is None:
        raise NotFoundError(f"The '{ADMIN_ROLE_NAME}' role is not seeded — run app/db/seed.py")
    return role_id


def _to_read(lob: Lob) -> LobRead:
    return LobRead(
        id=lob.id,
        name=lob.name,
        created_by=lob.created_by.username if lob.created_by else None,
        created_at=lob.created_at,
    )


async def _get_lob(db: DbSession, lob_id: uuid.UUID) -> Lob:
    stmt = select(Lob).options(selectinload(Lob.created_by)).where(Lob.id == lob_id)
    lob = (await db.execute(stmt)).scalar_one_or_none()
    if lob is None:
        raise NotFoundError("LOB not found")
    return lob


async def _scope_names(db: DbSession, scope_id: uuid.UUID, *, admins: bool) -> list[str]:
    stmt = (
        select(User.username)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.scope_type == ScopeType.LOB,
            Membership.scope_id == scope_id,
            Membership.role_id.is_not(None) if admins else Membership.role_id.is_(None),
        )
        .order_by(User.username)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=LobRead, status_code=201, dependencies=[_MANAGE])
async def create_lob(body: LobCreate, current_user: CurrentUser, db: DbSession) -> LobRead:
    existing = await db.execute(select(Lob.id).where(Lob.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("A LOB with this name already exists.")

    lob = Lob(name=body.name, created_by_id=current_user.id)
    db.add(lob)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="lob.created",
            entity_type="lob",
            entity_id=str(lob.id),
            detail={"name": lob.name},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A LOB with this name already exists.") from exc

    lob = await _get_lob(db, lob.id)
    return _to_read(lob)


@router.get("", response_model=list[LobRead])
async def list_lobs(db: DbSession) -> list[LobRead]:
    stmt = select(Lob).options(selectinload(Lob.created_by)).order_by(Lob.name)
    result = await db.execute(stmt)
    return [_to_read(lob) for lob in result.scalars().all()]


@router.get("/{lob_id}", response_model=LobRead)
async def get_lob(lob_id: uuid.UUID, db: DbSession) -> LobRead:
    lob = await _get_lob(db, lob_id)
    return _to_read(lob)


@router.patch("/{lob_id}", response_model=LobRead, dependencies=[_MANAGE])
async def rename_lob(
    lob_id: uuid.UUID, body: LobUpdate, current_user: CurrentUser, db: DbSession
) -> LobRead:
    lob = await _get_lob(db, lob_id)
    if body.name != lob.name:
        existing = await db.execute(select(Lob.id).where(Lob.name == body.name, Lob.id != lob_id))
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("A LOB with this name already exists.")
        old_name = lob.name
        lob.name = body.name
        try:
            await db.flush()
            await record_audit_log(
                db,
                actor_user_id=current_user.id,
                action="lob.updated",
                entity_type="lob",
                entity_id=str(lob.id),
                detail={"old_name": old_name, "new_name": lob.name},
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("A LOB with this name already exists.") from exc

    lob = await _get_lob(db, lob_id)
    return _to_read(lob)


@router.delete("/{lob_id}", status_code=204, dependencies=[_MANAGE])
async def delete_lob(lob_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> None:
    lob = await _get_lob(db, lob_id)
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="lob.deleted",
        entity_type="lob",
        entity_id=str(lob.id),
        detail={"name": lob.name},
    )
    await db.delete(lob)
    await db.commit()


@router.get("/{lob_id}/admins", response_model=list[str])
async def list_lob_admins(lob_id: uuid.UUID, db: DbSession) -> list[str]:
    await _get_lob(db, lob_id)
    return await _scope_names(db, lob_id, admins=True)


@router.get("/{lob_id}/members", response_model=list[str])
async def list_lob_members(lob_id: uuid.UUID, db: DbSession) -> list[str]:
    await _get_lob(db, lob_id)
    return await _scope_names(db, lob_id, admins=False)


async def _add_membership(
    db: DbSession,
    lob_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    role_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    action: str,
) -> None:
    membership = Membership(
        user_id=user_id, scope_type=ScopeType.LOB, scope_id=lob_id, role_id=role_id
    )
    db.add(membership)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="lob",
            entity_id=str(lob_id),
            detail={"user_id": str(user_id)},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("This user already has that membership.") from exc


async def _remove_membership(
    db: DbSession,
    lob_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    admins: bool,
    actor_user_id: uuid.UUID,
    action: str,
) -> None:
    stmt = select(Membership).where(
        Membership.scope_type == ScopeType.LOB,
        Membership.scope_id == lob_id,
        Membership.user_id == user_id,
        Membership.role_id.is_not(None) if admins else Membership.role_id.is_(None),
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    if membership is None:
        raise NotFoundError("Membership not found")
    await db.delete(membership)
    await record_audit_log(
        db,
        actor_user_id=actor_user_id,
        action=action,
        entity_type="lob",
        entity_id=str(lob_id),
        detail={"user_id": str(user_id)},
    )
    await db.commit()


@router.post("/{lob_id}/members", status_code=204, dependencies=[_MANAGE])
async def add_lob_member(
    lob_id: uuid.UUID, body: MembershipUserRef, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_lob(db, lob_id)
    await _add_membership(
        db,
        lob_id,
        body.user_id,
        role_id=None,
        actor_user_id=current_user.id,
        action="lob.member_added",
    )


@router.delete("/{lob_id}/members/{user_id}", status_code=204, dependencies=[_MANAGE])
async def remove_lob_member(
    lob_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_lob(db, lob_id)
    await _remove_membership(
        db,
        lob_id,
        user_id,
        admins=False,
        actor_user_id=current_user.id,
        action="lob.member_removed",
    )


@router.post("/{lob_id}/admins", status_code=204, dependencies=[_MANAGE])
async def add_lob_admin(
    lob_id: uuid.UUID, body: MembershipUserRef, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_lob(db, lob_id)
    admin_role_id = await _get_admin_role_id(db)
    await _add_membership(
        db,
        lob_id,
        body.user_id,
        role_id=admin_role_id,
        actor_user_id=current_user.id,
        action="lob.admin_added",
    )


@router.delete("/{lob_id}/admins/{user_id}", status_code=204, dependencies=[_MANAGE])
async def remove_lob_admin(
    lob_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_lob(db, lob_id)
    await _remove_membership(
        db, lob_id, user_id, admins=True, actor_user_id=current_user.id, action="lob.admin_removed"
    )
