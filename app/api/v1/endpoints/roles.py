"""Role CRUD. A Role is a named bundle of Privileges (`app/models/
security.py`'s existing `role_privileges` M2M from Phase 1) — Phase 3
adds the endpoints to manage that bundle directly, matching the old
backend's create_role (`role_privilege: string[]` at creation/update).

Privilege names are NOT free text here: `RoleCreate`/`RoleUpdate` only
accept names that already exist in the `privileges` table, seeded once
in app/db/seed.py from the old backend's real, closed catalog
(create_recon, read_recon, update_recon, ... — see seed.py). Passing an
unknown name is a clean 400, not a silently-ignored no-op or an
auto-created Privilege row — the catalog is closed by design, matching
the old backend's frontend (a fixed multi-select, not a free-text
field)."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.permissions import require_privilege
from app.models.security import Privilege, Role
from app.schemas.security import RoleCreate, RoleRead, RoleUpdate

router = APIRouter(prefix="/roles", tags=["security"])

_MANAGE = require_privilege("security:manage")


def _to_read(role: Role) -> RoleRead:
    return RoleRead(id=role.id, name=role.name, privileges=sorted(p.name for p in role.privileges))


async def _get_role(db: DbSession, role_id: uuid.UUID) -> Role:
    stmt = select(Role).options(selectinload(Role.privileges)).where(Role.id == role_id)
    role = (await db.execute(stmt)).scalar_one_or_none()
    if role is None:
        raise NotFoundError("Role not found")
    return role


async def _resolve_privileges(db: DbSession, names: list[str]) -> list[Privilege]:
    if not names:
        return []
    stmt = select(Privilege).where(Privilege.name.in_(names))
    found = (await db.execute(stmt)).scalars().all()
    missing = set(names) - {p.name for p in found}
    if missing:
        # A bare `pydantic.ValidationError` raised here would NOT be
        # caught by FastAPI's RequestValidationError handler (that class
        # only covers request-parsing failures) — it would fall through
        # to the unhandled-exception 500 handler instead. AppError is the
        # one exception type every endpoint in this codebase raises for a
        # client-caused 4xx, precisely so this can't happen.
        raise AppError(f"Unknown privilege name(s): {sorted(missing)}", code="unknown_privilege")
    return list(found)


@router.post("", response_model=RoleRead, status_code=201, dependencies=[_MANAGE])
async def create_role(body: RoleCreate, current_user: CurrentUser, db: DbSession) -> RoleRead:
    existing = await db.execute(select(Role.id).where(Role.name == body.name))
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("A role with this name already exists.")

    privileges = await _resolve_privileges(db, body.privilege_names)
    role = Role(name=body.name, privileges=privileges)
    db.add(role)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="role.created",
            entity_type="role",
            entity_id=str(role.id),
            detail={"name": role.name},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A role with this name already exists.") from exc

    role = await _get_role(db, role.id)
    return _to_read(role)


@router.get("", response_model=list[RoleRead])
async def list_roles(db: DbSession) -> list[RoleRead]:
    stmt = select(Role).options(selectinload(Role.privileges)).order_by(Role.name)
    result = await db.execute(stmt)
    return [_to_read(role) for role in result.scalars().all()]


@router.get("/{role_id}", response_model=RoleRead)
async def get_role(role_id: uuid.UUID, db: DbSession) -> RoleRead:
    role = await _get_role(db, role_id)
    return _to_read(role)


@router.patch("/{role_id}", response_model=RoleRead, dependencies=[_MANAGE])
async def update_role(
    role_id: uuid.UUID, body: RoleUpdate, current_user: CurrentUser, db: DbSession
) -> RoleRead:
    role = await _get_role(db, role_id)

    if body.name is not None and body.name != role.name:
        existing = await db.execute(
            select(Role.id).where(Role.name == body.name, Role.id != role_id)
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError("A role with this name already exists.")
        role.name = body.name

    if body.privilege_names is not None:
        role.privileges = await _resolve_privileges(db, body.privilege_names)

    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="role.updated",
            entity_type="role",
            entity_id=str(role.id),
            detail={"name": role.name},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A role with this name already exists.") from exc

    role = await _get_role(db, role_id)
    return _to_read(role)


@router.delete("/{role_id}", status_code=204, dependencies=[_MANAGE])
async def delete_role(role_id: uuid.UUID, current_user: CurrentUser, db: DbSession) -> None:
    role = await _get_role(db, role_id)
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="role.deleted",
        entity_type="role",
        entity_id=str(role.id),
        detail={"name": role.name},
    )
    await db.delete(role)
    await db.commit()
