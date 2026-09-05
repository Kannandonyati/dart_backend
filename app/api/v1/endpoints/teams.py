"""Team CRUD plus admin/member management. Single-parented to one Lob —
confirmed against the old backend's create_team, unlike Group (see
app/models/security.py's module docstring). Same `security:manage` gate
as lobs.py."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import require_privilege
from app.models.security import Lob, Membership, Role, ScopeType, Team
from app.models.user import User
from app.schemas.security import MembershipUserRef, TeamCreate, TeamRead, TeamUpdate

router = APIRouter(prefix="/teams", tags=["security"])

_MANAGE = require_privilege("security:manage")

ADMIN_ROLE_NAME = "Admin"


async def _get_admin_role_id(db: DbSession) -> uuid.UUID:
    role_id = (
        await db.execute(select(Role.id).where(Role.name == ADMIN_ROLE_NAME))
    ).scalar_one_or_none()
    if role_id is None:
        raise NotFoundError(f"The '{ADMIN_ROLE_NAME}' role is not seeded — run app/db/seed.py")
    return role_id


def _to_read(team: Team) -> TeamRead:
    return TeamRead(
        id=team.id,
        name=team.name,
        lob_id=team.lob_id,
        lob_name=team.lob.name,
        created_at=team.created_at,
    )


async def _get_team(db: DbSession, team_id: uuid.UUID) -> Team:
    stmt = select(Team).options(selectinload(Team.lob)).where(Team.id == team_id)
    team = (await db.execute(stmt)).scalar_one_or_none()
    if team is None:
        raise NotFoundError("Team not found")
    return team


async def _scope_names(db: DbSession, scope_id: uuid.UUID, *, admins: bool) -> list[str]:
    stmt = (
        select(User.username)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.scope_type == ScopeType.TEAM,
            Membership.scope_id == scope_id,
            Membership.role_id.is_not(None) if admins else Membership.role_id.is_(None),
        )
        .order_by(User.username)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=TeamRead, status_code=201, dependencies=[_MANAGE])
async def create_team(body: TeamCreate, current_user: CurrentUser, db: DbSession) -> TeamRead:
    lob = (await db.execute(select(Lob.id).where(Lob.id == body.lob_id))).scalar_one_or_none()
    if lob is None:
        raise NotFoundError("LOB not found")

    existing = await db.execute(
        select(Team.id).where(Team.lob_id == body.lob_id, Team.name == body.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("A team with this name already exists in this LOB.")

    team = Team(name=body.name, lob_id=body.lob_id)
    db.add(team)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="team.created",
            entity_type="team",
            entity_id=str(team.id),
            detail={"name": team.name},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A team with this name already exists in this LOB.") from exc

    team = await _get_team(db, team.id)
    return _to_read(team)


@router.get("", response_model=list[TeamRead])
async def list_teams(
    db: DbSession, lob_id: Annotated[uuid.UUID | None, Query()] = None
) -> list[TeamRead]:
    stmt = select(Team).options(selectinload(Team.lob)).order_by(Team.name)
    if lob_id is not None:
        stmt = stmt.where(Team.lob_id == lob_id)
    result = await db.execute(stmt)
    return [_to_read(team) for team in result.scalars().all()]


@router.get("/{team_id}", response_model=TeamRead)
async def get_team(team_id: uuid.UUID, db: DbSession) -> TeamRead:
    team = await _get_team(db, team_id)
    return _to_read(team)


@router.patch("/{team_id}", response_model=TeamRead, dependencies=[_MANAGE])
async def rename_team(
    team_id: uuid.UUID, body: TeamUpdate, current_user: CurrentUser, db: DbSession
) -> TeamRead:
    team = await _get_team(db, team_id)
    if body.name != team.name:
        existing = await db.execute(
            select(Team.id).where(
                Team.lob_id == team.lob_id, Team.name == body.name, Team.id != team_id
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("A team with this name already exists in this LOB.")
        old_name = team.name
        team.name = body.name
        try:
            await db.flush()
            await record_audit_log(
                db,
                actor_user_id=current_user.id,
                action="team.updated",
                entity_type="team",
                entity_id=str(team.id),
                detail={"old_name": old_name, "new_name": team.name},
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("A team with this name already exists in this LOB.") from exc

    team = await _get_team(db, team_id)
    return _to_read(team)


@router.delete("/{team_id}", status_code=204, dependencies=[_MANAGE])
async def delete_team(team_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> None:
    team = await _get_team(db, team_id)
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="team.deleted",
        entity_type="team",
        entity_id=str(team.id),
        detail={"name": team.name},
    )
    await db.delete(team)
    await db.commit()


@router.get("/{team_id}/admins", response_model=list[str])
async def list_team_admins(team_id: uuid.UUID, db: DbSession) -> list[str]:
    await _get_team(db, team_id)
    return await _scope_names(db, team_id, admins=True)


@router.get("/{team_id}/members", response_model=list[str])
async def list_team_members(team_id: uuid.UUID, db: DbSession) -> list[str]:
    await _get_team(db, team_id)
    return await _scope_names(db, team_id, admins=False)


async def _add_membership(
    db: DbSession,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    role_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    action: str,
) -> None:
    membership = Membership(
        user_id=user_id, scope_type=ScopeType.TEAM, scope_id=team_id, role_id=role_id
    )
    db.add(membership)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="team",
            entity_id=str(team_id),
            detail={"user_id": str(user_id)},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("This user already has that membership.") from exc


async def _remove_membership(
    db: DbSession,
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    admins: bool,
    actor_user_id: uuid.UUID,
    action: str,
) -> None:
    stmt = select(Membership).where(
        Membership.scope_type == ScopeType.TEAM,
        Membership.scope_id == team_id,
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
        entity_type="team",
        entity_id=str(team_id),
        detail={"user_id": str(user_id)},
    )
    await db.commit()


@router.post("/{team_id}/members", status_code=204, dependencies=[_MANAGE])
async def add_team_member(
    team_id: uuid.UUID, body: MembershipUserRef, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_team(db, team_id)
    await _add_membership(
        db,
        team_id,
        body.user_id,
        role_id=None,
        actor_user_id=current_user.id,
        action="team.member_added",
    )


@router.delete("/{team_id}/members/{user_id}", status_code=204, dependencies=[_MANAGE])
async def remove_team_member(
    team_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_team(db, team_id)
    await _remove_membership(
        db,
        team_id,
        user_id,
        admins=False,
        actor_user_id=current_user.id,
        action="team.member_removed",
    )


@router.post("/{team_id}/admins", status_code=204, dependencies=[_MANAGE])
async def add_team_admin(
    team_id: uuid.UUID, body: MembershipUserRef, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_team(db, team_id)
    admin_role_id = await _get_admin_role_id(db)
    await _add_membership(
        db,
        team_id,
        body.user_id,
        role_id=admin_role_id,
        actor_user_id=current_user.id,
        action="team.admin_added",
    )


@router.delete("/{team_id}/admins/{user_id}", status_code=204, dependencies=[_MANAGE])
async def remove_team_admin(
    team_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_team(db, team_id)
    await _remove_membership(
        db,
        team_id,
        user_id,
        admins=True,
        actor_user_id=current_user.id,
        action="team.admin_removed",
    )
