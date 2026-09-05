"""Global Variable catalog used by Manage Security group links."""

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import ConflictError
from app.core.permissions import require_privilege
from app.models.global_variable import GlobalVariable
from app.schemas.global_variable import GlobalVariableCreate, GlobalVariableRead

router = APIRouter(prefix="/global-variables", tags=["security"])
_MANAGE = require_privilege("security:manage")


@router.get("", response_model=list[GlobalVariableRead])
async def list_global_variables(db: DbSession) -> list[GlobalVariableRead]:
    stmt = select(GlobalVariable).order_by(GlobalVariable.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [GlobalVariableRead(name=row.name) for row in rows]


@router.post("", response_model=GlobalVariableRead, status_code=201, dependencies=[_MANAGE])
async def create_global_variable(
    body: GlobalVariableCreate, current_user: CurrentUser, db: DbSession
) -> GlobalVariableRead:
    row = GlobalVariable(name=body.name.strip())
    db.add(row)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="global_variable.created",
            entity_type="global_variable",
            entity_id=str(row.id),
            detail={"name": row.name},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A global variable with this name already exists.") from exc
    return GlobalVariableRead(name=row.name)
