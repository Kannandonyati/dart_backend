"""Bridge Run — starts the Celery computation (app/tasks/bridge_tasks.py),
tracks its status, and reads back the resolved/kickout-flagged data.

Route order: `/data` is registered before `/{bridge_run_id}` — same
literal-before-parameterized rule every prior phase has needed.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.exceptions import NotFoundError
from app.core.recon_access import get_accessible_recon
from app.models.bridge import BridgeRun
from app.schemas.bridge import BridgeRunRead
from app.tasks.bridge_tasks import run_bridge_task

router = APIRouter(prefix="/recons/{recon_id}/bridge-runs", tags=["bridge-members"])


def _to_read(run: BridgeRun) -> BridgeRunRead:
    return BridgeRunRead(
        id=run.id,
        recon_id=run.recon_id,
        status=run.status,
        total_rows=run.total_rows,
        processed_rows=run.processed_rows,
        kickout_count=run.kickout_count,
        error_message=run.error_message,
        created_by=run.created_by.username,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@router.post("", response_model=BridgeRunRead, status_code=201)
async def start_bridge_run(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> BridgeRunRead:
    await get_accessible_recon(db, current_user, recon_id)

    run = BridgeRun(recon_id=recon_id, created_by_id=current_user.id)
    db.add(run)
    await db.commit()

    run_bridge_task.delay(str(run.id))

    stmt = (
        select(BridgeRun).options(selectinload(BridgeRun.created_by)).where(BridgeRun.id == run.id)
    )
    run = (await db.execute(stmt)).scalar_one()
    return _to_read(run)


@router.get("", response_model=list[BridgeRunRead])
async def list_bridge_runs(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[BridgeRunRead]:
    await get_accessible_recon(db, current_user, recon_id)
    total = (
        await db.execute(
            select(func.count()).select_from(BridgeRun).where(BridgeRun.recon_id == recon_id)
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    stmt = (
        select(BridgeRun)
        .options(selectinload(BridgeRun.created_by))
        .where(BridgeRun.recon_id == recon_id)
        .order_by(BridgeRun.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    result = await db.execute(stmt)
    return [_to_read(r) for r in result.scalars().all()]


@router.get("/{bridge_run_id}", response_model=BridgeRunRead)
async def get_bridge_run(
    recon_id: uuid.UUID, bridge_run_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> BridgeRunRead:
    await get_accessible_recon(db, current_user, recon_id)
    stmt = (
        select(BridgeRun)
        .options(selectinload(BridgeRun.created_by))
        .where(BridgeRun.id == bridge_run_id, BridgeRun.recon_id == recon_id)
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Bridge run not found")
    return _to_read(run)
