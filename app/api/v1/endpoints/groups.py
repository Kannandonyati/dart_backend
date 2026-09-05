"""Group CRUD, admin/member management, and Lob/Team/Role/Recon linking.

Group is standalone (name only at creation) and many-to-many with Lob,
Team, and Role — confirmed against the old backend's actual
create_group/add_lob_grp/add_team_grp/add_role_group endpoints and the
existing frontend's GroupDetails (lobNames/teamNames/roleNames are all
arrays); see app/models/security.py's module docstring for the full
correction from Phase 1's original (wrong) single-parent-to-Team model.

`GET /groups/mine` backs the recon-creation group dropdown — see
app/api/v1/endpoints/recons.py and the old backend's
get_group_names_list.py (`fetch_data: "group_member"`, filtered by the
caller's own username): the groups a user can create a recon under are
exactly the groups they hold ANY membership in (admin or plain member),
not groups generally.
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
from app.models.global_variable import GlobalVariable, group_global_variables
from app.models.recon import Recon, recon_group_xref
from app.models.security import Group, Lob, Membership, Role, ScopeType, Team
from app.models.user import User
from app.schemas.global_variable import GlobalVariableCreate
from app.schemas.security import (
    GroupCreate,
    GroupDetails,
    GroupRead,
    GroupUpdate,
    MembershipUserRef,
)

router = APIRouter(prefix="/groups", tags=["security"])

_MANAGE = require_privilege("security:manage")

ADMIN_ROLE_NAME = "Admin"


async def _get_admin_role_id(db: DbSession) -> uuid.UUID:
    role_id = (
        await db.execute(select(Role.id).where(Role.name == ADMIN_ROLE_NAME))
    ).scalar_one_or_none()
    if role_id is None:
        raise NotFoundError(f"The '{ADMIN_ROLE_NAME}' role is not seeded — run app/db/seed.py")
    return role_id


def _to_read(group: Group) -> GroupRead:
    return GroupRead(
        id=group.id,
        name=group.name,
        created_by=group.created_by.username if group.created_by else None,
        created_at=group.created_at,
    )


async def _get_group(db: DbSession, group_id: uuid.UUID) -> Group:
    stmt = (
        select(Group)
        .options(
            selectinload(Group.created_by),
            selectinload(Group.lobs),
            selectinload(Group.teams),
            selectinload(Group.roles),
        )
        .where(Group.id == group_id)
    )
    group = (await db.execute(stmt)).scalar_one_or_none()
    if group is None:
        raise NotFoundError("Group not found")
    return group


async def _scope_names(db: DbSession, group_id: uuid.UUID, *, admins: bool) -> list[str]:
    stmt = (
        select(User.username)
        .join(Membership, Membership.user_id == User.id)
        .where(
            Membership.scope_type == ScopeType.GROUP,
            Membership.scope_id == group_id,
            Membership.role_id.is_not(None) if admins else Membership.role_id.is_(None),
        )
        .order_by(User.username)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _recon_names(db: DbSession, group_id: uuid.UUID) -> list[str]:
    stmt = (
        select(Recon.name)
        .join(recon_group_xref, recon_group_xref.c.recon_id == Recon.id)
        .where(recon_group_xref.c.group_id == group_id, Recon.deleted_at.is_(None))
        .order_by(Recon.name)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _gv_names(db: DbSession, group_id: uuid.UUID) -> list[str]:
    stmt = (
        select(GlobalVariable.name)
        .join(
            group_global_variables,
            group_global_variables.c.global_variable_id == GlobalVariable.id,
        )
        .where(group_global_variables.c.group_id == group_id)
        .order_by(GlobalVariable.name)
    )
    return list((await db.execute(stmt)).scalars().all())


@router.post("", response_model=GroupRead, status_code=201, dependencies=[_MANAGE])
async def create_group(body: GroupCreate, current_user: CurrentUser, db: DbSession) -> GroupRead:
    existing = await db.execute(select(Group.id).where(Group.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("A group with this name already exists.")

    group = Group(name=body.name, created_by_id=current_user.id)
    db.add(group)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="group.created",
            entity_type="group",
            entity_id=str(group.id),
            detail={"name": group.name},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A group with this name already exists.") from exc

    group = await _get_group(db, group.id)
    return _to_read(group)


@router.get("", response_model=list[GroupRead])
async def list_groups(db: DbSession) -> list[GroupRead]:
    stmt = select(Group).options(selectinload(Group.created_by)).order_by(Group.name)
    result = await db.execute(stmt)
    return [_to_read(group) for group in result.scalars().all()]


@router.get("/mine", response_model=list[GroupRead])
async def list_my_groups(current_user: CurrentUser, db: DbSession) -> list[GroupRead]:
    stmt = (
        select(Group)
        .options(selectinload(Group.created_by))
        .join(Membership, Membership.scope_id == Group.id)
        .where(Membership.scope_type == ScopeType.GROUP, Membership.user_id == current_user.id)
        .order_by(Group.name)
    )
    result = await db.execute(stmt)
    return [_to_read(group) for group in result.scalars().unique().all()]


@router.get("/{group_id}", response_model=GroupRead)
async def get_group(group_id: uuid.UUID, db: DbSession) -> GroupRead:
    group = await _get_group(db, group_id)
    return _to_read(group)


@router.get("/{group_id}/details", response_model=GroupDetails)
async def get_group_details(group_id: uuid.UUID, db: DbSession) -> GroupDetails:
    group = await _get_group(db, group_id)
    return GroupDetails(
        id=group.id,
        name=group.name,
        admin_names=await _scope_names(db, group_id, admins=True),
        member_names=await _scope_names(db, group_id, admins=False),
        lob_names=sorted(lob.name for lob in group.lobs),
        team_names=sorted(team.name for team in group.teams),
        role_names=sorted(role.name for role in group.roles),
        recon_names=await _recon_names(db, group_id),
        gv_names=await _gv_names(db, group_id),
    )


@router.patch("/{group_id}", response_model=GroupRead, dependencies=[_MANAGE])
async def rename_group(
    group_id: uuid.UUID, body: GroupUpdate, current_user: CurrentUser, db: DbSession
) -> GroupRead:
    group = await _get_group(db, group_id)
    if body.name != group.name:
        existing = await db.execute(
            select(Group.id).where(Group.name == body.name, Group.id != group_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("A group with this name already exists.")
        old_name = group.name
        group.name = body.name
        try:
            await db.flush()
            await record_audit_log(
                db,
                actor_user_id=current_user.id,
                action="group.updated",
                entity_type="group",
                entity_id=str(group.id),
                detail={"old_name": old_name, "new_name": group.name},
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("A group with this name already exists.") from exc

    group = await _get_group(db, group_id)
    return _to_read(group)


@router.delete("/{group_id}", status_code=204, dependencies=[_MANAGE])
async def delete_group(group_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> None:
    group = await _get_group(db, group_id)
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="group.deleted",
        entity_type="group",
        entity_id=str(group.id),
        detail={"name": group.name},
    )
    await db.delete(group)
    await db.commit()


@router.get("/{group_id}/admins", response_model=list[str])
async def list_group_admins(group_id: uuid.UUID, db: DbSession) -> list[str]:
    await _get_group(db, group_id)
    return await _scope_names(db, group_id, admins=True)


@router.get("/{group_id}/members", response_model=list[str])
async def list_group_members(group_id: uuid.UUID, db: DbSession) -> list[str]:
    await _get_group(db, group_id)
    return await _scope_names(db, group_id, admins=False)


async def _add_membership(
    db: DbSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    role_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    action: str,
) -> None:
    membership = Membership(
        user_id=user_id, scope_type=ScopeType.GROUP, scope_id=group_id, role_id=role_id
    )
    db.add(membership)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=actor_user_id,
            action=action,
            entity_type="group",
            entity_id=str(group_id),
            detail={"user_id": str(user_id)},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("This user already has that membership.") from exc


async def _remove_membership(
    db: DbSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    admins: bool,
    actor_user_id: uuid.UUID,
    action: str,
) -> None:
    stmt = select(Membership).where(
        Membership.scope_type == ScopeType.GROUP,
        Membership.scope_id == group_id,
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
        entity_type="group",
        entity_id=str(group_id),
        detail={"user_id": str(user_id)},
    )
    await db.commit()


@router.post("/{group_id}/members", status_code=204, dependencies=[_MANAGE])
async def add_group_member(
    group_id: uuid.UUID, body: MembershipUserRef, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_group(db, group_id)
    await _add_membership(
        db,
        group_id,
        body.user_id,
        role_id=None,
        actor_user_id=current_user.id,
        action="group.member_added",
    )


@router.delete("/{group_id}/members/{user_id}", status_code=204, dependencies=[_MANAGE])
async def remove_group_member(
    group_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_group(db, group_id)
    await _remove_membership(
        db,
        group_id,
        user_id,
        admins=False,
        actor_user_id=current_user.id,
        action="group.member_removed",
    )


@router.post("/{group_id}/admins", status_code=204, dependencies=[_MANAGE])
async def add_group_admin(
    group_id: uuid.UUID, body: MembershipUserRef, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_group(db, group_id)
    admin_role_id = await _get_admin_role_id(db)
    await _add_membership(
        db,
        group_id,
        body.user_id,
        role_id=admin_role_id,
        actor_user_id=current_user.id,
        action="group.admin_added",
    )


@router.delete("/{group_id}/admins/{user_id}", status_code=204, dependencies=[_MANAGE])
async def remove_group_admin(
    group_id: uuid.UUID, user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_group(db, group_id)
    await _remove_membership(
        db,
        group_id,
        user_id,
        admins=True,
        actor_user_id=current_user.id,
        action="group.admin_removed",
    )


@router.post("/{group_id}/lobs/{lob_id}", status_code=204, dependencies=[_MANAGE])
async def link_group_lob(
    group_id: uuid.UUID, lob_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    group = await _get_group(db, group_id)
    lob = (await db.execute(select(Lob).where(Lob.id == lob_id))).scalar_one_or_none()
    if lob is None:
        raise NotFoundError("LOB not found")
    if lob not in group.lobs:
        group.lobs.append(lob)
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="group.lob_linked",
            entity_type="group",
            entity_id=str(group_id),
            detail={"lob_id": str(lob_id)},
        )
        await db.commit()


@router.delete("/{group_id}/lobs/{lob_id}", status_code=204, dependencies=[_MANAGE])
async def unlink_group_lob(
    group_id: uuid.UUID, lob_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    group = await _get_group(db, group_id)
    group.lobs = [lob for lob in group.lobs if lob.id != lob_id]
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="group.lob_unlinked",
        entity_type="group",
        entity_id=str(group_id),
        detail={"lob_id": str(lob_id)},
    )
    await db.commit()


@router.post("/{group_id}/teams/{team_id}", status_code=204, dependencies=[_MANAGE])
async def link_group_team(
    group_id: uuid.UUID, team_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    group = await _get_group(db, group_id)
    team = (await db.execute(select(Team).where(Team.id == team_id))).scalar_one_or_none()
    if team is None:
        raise NotFoundError("Team not found")
    if team not in group.teams:
        group.teams.append(team)
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="group.team_linked",
            entity_type="group",
            entity_id=str(group_id),
            detail={"team_id": str(team_id)},
        )
        await db.commit()


@router.delete("/{group_id}/teams/{team_id}", status_code=204, dependencies=[_MANAGE])
async def unlink_group_team(
    group_id: uuid.UUID, team_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    group = await _get_group(db, group_id)
    group.teams = [team for team in group.teams if team.id != team_id]
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="group.team_unlinked",
        entity_type="group",
        entity_id=str(group_id),
        detail={"team_id": str(team_id)},
    )
    await db.commit()


@router.post("/{group_id}/roles/{role_id}", status_code=204, dependencies=[_MANAGE])
async def link_group_role(
    group_id: uuid.UUID, role_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    group = await _get_group(db, group_id)
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found")
    if role not in group.roles:
        group.roles.append(role)
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="group.role_linked",
            entity_type="group",
            entity_id=str(group_id),
            detail={"role_id": str(role_id)},
        )
        await db.commit()


@router.delete("/{group_id}/roles/{role_id}", status_code=204, dependencies=[_MANAGE])
async def unlink_group_role(
    group_id: uuid.UUID, role_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    group = await _get_group(db, group_id)
    group.roles = [role for role in group.roles if role.id != role_id]
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="group.role_unlinked",
        entity_type="group",
        entity_id=str(group_id),
        detail={"role_id": str(role_id)},
    )
    await db.commit()


@router.post("/{group_id}/global-variables", status_code=204, dependencies=[_MANAGE])
async def link_group_global_variable(
    group_id: uuid.UUID,
    body: GlobalVariableCreate,
    current_user: CurrentUser,
    db: DbSession,
) -> None:
    await _get_group(db, group_id)
    name = body.name.strip()
    gv = (
        await db.execute(select(GlobalVariable).where(GlobalVariable.name == name))
    ).scalar_one_or_none()
    if gv is None:
        gv = GlobalVariable(name=name)
        db.add(gv)
        await db.flush()

    existing = await db.execute(
        select(group_global_variables.c.group_id).where(
            group_global_variables.c.group_id == group_id,
            group_global_variables.c.global_variable_id == gv.id,
        )
    )
    if existing.first() is None:
        await db.execute(
            group_global_variables.insert().values(group_id=group_id, global_variable_id=gv.id)
        )
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="group.gv_linked",
            entity_type="group",
            entity_id=str(group_id),
            detail={"name": name},
        )
        await db.commit()


@router.delete("/{group_id}/global-variables/{gv_name}", status_code=204, dependencies=[_MANAGE])
async def unlink_group_global_variable(
    group_id: uuid.UUID, gv_name: str, current_user: CurrentUser, db: DbSession
) -> None:
    await _get_group(db, group_id)
    gv = (
        await db.execute(select(GlobalVariable).where(GlobalVariable.name == gv_name))
    ).scalar_one_or_none()
    if gv is None:
        raise NotFoundError("Global variable not found")
    await db.execute(
        group_global_variables.delete().where(
            group_global_variables.c.group_id == group_id,
            group_global_variables.c.global_variable_id == gv.id,
        )
    )
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="group.gv_unlinked",
        entity_type="group",
        entity_id=str(group_id),
        detail={"name": gv_name},
    )
    await db.commit()
