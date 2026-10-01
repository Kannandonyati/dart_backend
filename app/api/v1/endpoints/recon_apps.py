"""Recon App CRUD — import/parsing settings per source application on a
recon's Dimension Linking stage (delimiter, currency format, header
row). A recon is seeded with apps 1 and 2; Dimension Linking can add
more, up to MAX_RECON_APPS (old DART cap). Access follows the recon
they belong to via app/core/recon_access.py.

Create is create-only (409 on a duplicate app_number), not the old
backend's upsert-by-`(recon_name, app_type)` — matches every other
create endpoint in this codebase (create_user, create_recon,
create_lob, ...); a deliberate, consistent simplification, not an
oversight.
"""

import uuid

from fastapi import APIRouter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.core.recon_access import get_accessible_recon
from app.core.recon_limits import MAX_RECON_APPS
from app.models.dimension import Dimension, DimensionMapping, ReconApp
from app.models.global_variable import GlobalVariable
from app.schemas.dimension import ReconAppCreate, ReconAppRead, ReconAppUpdate
from app.services.recon_app_delete import delete_recon_app

router = APIRouter(prefix="/recons/{recon_id}/apps", tags=["dimension-linking"])


def _to_read(app: ReconApp, gv_name: str | None = None) -> ReconAppRead:
    return ReconAppRead(
        id=app.id,
        recon_id=app.recon_id,
        app_number=app.app_number,
        name=app.name,
        description=app.description,
        delimiter=app.delimiter,
        currency_delimiter=app.currency_delimiter,
        currency_symbol=app.currency_symbol,
        thousands_separator=app.thousands_separator,
        has_header=app.has_header,
        global_variable_id=app.global_variable_id,
        global_variable_name=gv_name,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


async def _gv_names(db: DbSession, apps: list[ReconApp]) -> dict[uuid.UUID, str]:
    ids = {app.global_variable_id for app in apps if app.global_variable_id}
    if not ids:
        return {}
    rows = (await db.execute(select(GlobalVariable).where(GlobalVariable.id.in_(ids)))).scalars()
    return {row.id: row.name for row in rows}


async def _get_app(db: DbSession, recon_id: uuid.UUID, app_number: int) -> ReconApp:
    stmt = select(ReconApp).where(ReconApp.recon_id == recon_id, ReconApp.app_number == app_number)
    app = (await db.execute(stmt)).scalar_one_or_none()
    if app is None:
        raise NotFoundError("Recon app not found")
    return app


@router.post("", response_model=ReconAppRead, status_code=201)
async def create_recon_app(
    recon_id: uuid.UUID, body: ReconAppCreate, current_user: CurrentUser, db: DbSession
) -> ReconAppRead:
    await get_accessible_recon(db, current_user, recon_id)

    existing_count = (
        await db.execute(
            select(func.count()).select_from(ReconApp).where(ReconApp.recon_id == recon_id)
        )
    ).scalar_one()
    if existing_count >= MAX_RECON_APPS:
        raise ConflictError(f"Maximum of {MAX_RECON_APPS} applications reached.")

    name_taken = (
        await db.execute(
            select(ReconApp.id).where(
                ReconApp.recon_id == recon_id,
                func.lower(ReconApp.name) == body.name.strip().lower(),
            )
        )
    ).scalar_one_or_none()
    if name_taken is not None:
        raise ConflictError("Application name already exists in this recon.")

    existing = await db.execute(
        select(ReconApp.id).where(
            ReconApp.recon_id == recon_id, ReconApp.app_number == body.app_number
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f"App {body.app_number} already exists for this recon.")

    app = ReconApp(recon_id=recon_id, **body.model_dump())
    db.add(app)
    dimensions = (
        (await db.execute(select(Dimension).where(Dimension.recon_id == recon_id))).scalars().all()
    )
    for dimension in dimensions:
        db.add(
            DimensionMapping(
                dimension_id=dimension.id,
                app_number=body.app_number,
                in_file=False,
                default_value="",
                is_active=True,
            )
        )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(f"App {body.app_number} already exists for this recon.") from exc

    await db.refresh(app)
    return _to_read(app)


@router.get("", response_model=list[ReconAppRead])
async def list_recon_apps(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> list[ReconAppRead]:
    await get_accessible_recon(db, current_user, recon_id)
    stmt = select(ReconApp).where(ReconApp.recon_id == recon_id).order_by(ReconApp.app_number)
    result = await db.execute(stmt)
    apps = list(result.scalars().all())
    names = await _gv_names(db, apps)
    return [
        _to_read(app, names.get(app.global_variable_id) if app.global_variable_id else None)
        for app in apps
    ]


@router.patch("/{app_number}", response_model=ReconAppRead)
async def update_recon_app(
    recon_id: uuid.UUID,
    app_number: int,
    body: ReconAppUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> ReconAppRead:
    await get_accessible_recon(db, current_user, recon_id)
    app = await _get_app(db, recon_id, app_number)
    payload = body.model_dump(exclude_unset=True)
    gv_id = payload.pop("global_variable_id", "__omit__")
    for field, value in payload.items():
        setattr(app, field, value)
    if gv_id != "__omit__":
        if gv_id is not None:
            gv = (
                await db.execute(select(GlobalVariable).where(GlobalVariable.id == gv_id))
            ).scalar_one_or_none()
            if gv is None:
                raise NotFoundError("Global variable not found")
        app.global_variable_id = gv_id

    await db.commit()
    await db.refresh(app)
    names = await _gv_names(db, [app])
    return _to_read(app, names.get(app.global_variable_id) if app.global_variable_id else None)


@router.delete("/{app_number}", status_code=204)
async def remove_recon_app(
    recon_id: uuid.UUID, app_number: int, current_user: CurrentUser, db: DbSession
) -> None:
    await get_accessible_recon(db, current_user, recon_id)
    await delete_recon_app(db, recon_id, app_number)
    await db.commit()
