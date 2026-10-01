"""Workflow Scheduler HTTP surface — definitions, pause/trigger, run history.

Additive `/api/v1/workflows` (and `/api/v1/workflow-runs` for monitoring).
Access is the same recon ownership rule as the pipeline: 404, never 403.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.audit import record_audit_log
from app.core.config import settings
from app.core.exceptions import ConflictError
from app.core.recon_access import can_manage_recon, get_accessible_recon
from app.models.recon import Recon
from app.models.workflow import Workflow, WorkflowRun, WorkflowTriggerKind
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowRead,
    WorkflowRunRead,
    WorkflowUpdate,
)
from app.services.workflow_access import get_accessible_run, get_accessible_workflow
from app.services.workflow_definition import definition_for_recon, validated_definition
from app.services.workflow_dispatch import dispatch_run
from app.services.workflow_queue import queue_workflow_run, reload_run, run_to_read
from app.services.workflow_runner import run_workflow
from app.services.workflow_schedule import is_once_schedule, next_scheduled_at

router = APIRouter(prefix="/workflows", tags=["workflow-scheduler"])
runs_router = APIRouter(prefix="/workflow-runs", tags=["workflow-scheduler"])


def _to_read(workflow: Workflow, latest_run: WorkflowRun | None = None) -> WorkflowRead:
    return WorkflowRead(
        id=workflow.id,
        name=workflow.name,
        recon_id=workflow.recon_id,
        recon_name=workflow.recon.name,
        definition=workflow.definition,
        schedule_cron=workflow.schedule_cron,
        timezone=workflow.timezone,
        is_paused=workflow.is_paused,
        next_run_at=workflow.next_run_at,
        created_by=workflow.created_by.username,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        latest_run=run_to_read(latest_run) if latest_run is not None else None,
    )


def _next_run(cron: str | None, timezone: str, paused: bool) -> datetime | None:
    if paused:
        return None
    return next_scheduled_at(cron, timezone, datetime.now(UTC))


async def _live_name_taken(db: DbSession, name: str, exclude_id: uuid.UUID | None = None) -> bool:
    stmt = select(Workflow.id).where(Workflow.name == name, Workflow.deleted_at.is_(None))
    if exclude_id is not None:
        stmt = stmt.where(Workflow.id != exclude_id)
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _latest_runs(db: DbSession, workflow_ids: list[uuid.UUID]) -> dict[uuid.UUID, WorkflowRun]:
    if not workflow_ids:
        return {}
    stmt = (
        select(WorkflowRun)
        .options(
            selectinload(WorkflowRun.triggered_by),
            selectinload(WorkflowRun.steps),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.created_by),
            selectinload(WorkflowRun.workflow),
        )
        .where(WorkflowRun.workflow_id.in_(workflow_ids))
        .order_by(WorkflowRun.created_at.desc())
    )
    latest: dict[uuid.UUID, WorkflowRun] = {}
    for run in (await db.execute(stmt)).unique().scalars().all():
        if run.workflow_id not in latest:
            latest[run.workflow_id] = run
    return latest


async def _reload(db: DbSession, workflow_id: uuid.UUID) -> Workflow:
    stmt = (
        select(Workflow)
        .options(selectinload(Workflow.recon), selectinload(Workflow.created_by))
        .where(Workflow.id == workflow_id)
    )
    return (await db.execute(stmt)).scalar_one()


@router.post("", response_model=WorkflowRead, status_code=201)
async def create_workflow(
    body: WorkflowCreate, current_user: CurrentUser, db: DbSession
) -> WorkflowRead:
    await get_accessible_recon(db, current_user, body.recon_id)
    if await _live_name_taken(db, body.name):
        raise ConflictError("A workflow with this name already exists.")
    workflow = Workflow(
        name=body.name,
        recon_id=body.recon_id,
        definition=await definition_for_recon(db, body.recon_id)
        if body.definition is None
        else validated_definition(body.definition),
        schedule_cron=body.schedule_cron,
        timezone=body.timezone,
        is_paused=body.is_paused,
        next_run_at=_next_run(body.schedule_cron, body.timezone, body.is_paused),
        created_by_id=current_user.id,
    )
    db.add(workflow)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A workflow with this name already exists.") from exc
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="workflow.created",
        recon_id=workflow.recon_id,
        entity_type="workflow",
        entity_id=str(workflow.id),
        detail={"name": workflow.name},
    )
    await db.commit()
    return _to_read(await _reload(db, workflow.id))


@router.get("", response_model=list[WorkflowRead])
async def list_workflows(
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[WorkflowRead]:
    stmt = (
        select(Workflow)
        .options(
            selectinload(Workflow.recon).selectinload(Recon.owner),
            selectinload(Workflow.recon).selectinload(Recon.groups),
            selectinload(Workflow.created_by),
        )
        .where(Workflow.deleted_at.is_(None))
        .order_by(Workflow.updated_at.desc())
    )
    rows = list((await db.execute(stmt)).unique().scalars().all())
    visible = [w for w in rows if await can_manage_recon(db, current_user, w.recon)]
    response.headers["X-Total-Count"] = str(len(visible))
    start = pagination["offset"]
    end = start + pagination["page_size"]
    page = visible[start:end]
    latest = await _latest_runs(db, [w.id for w in page])
    return [_to_read(w, latest.get(w.id)) for w in page]


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(
    workflow_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> WorkflowRead:
    workflow = await get_accessible_workflow(db, current_user, workflow_id)
    latest = await _latest_runs(db, [workflow.id])
    return _to_read(workflow, latest.get(workflow.id))


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: uuid.UUID, body: WorkflowUpdate, current_user: CurrentUser, db: DbSession
) -> WorkflowRead:
    workflow = await get_accessible_workflow(db, current_user, workflow_id)
    previous_cron = workflow.schedule_cron
    previous_next = workflow.next_run_at
    previous_tz = workflow.timezone
    if body.name is not None and body.name != workflow.name:
        if await _live_name_taken(db, body.name, exclude_id=workflow.id):
            raise ConflictError("A workflow with this name already exists.")
        workflow.name = body.name
    if body.definition is not None:
        workflow.definition = validated_definition(body.definition)
    if "schedule_cron" in body.model_fields_set:
        workflow.schedule_cron = body.schedule_cron or None
    if body.timezone is not None:
        workflow.timezone = body.timezone
    if body.is_paused is not None:
        workflow.is_paused = body.is_paused
    same_once = (
        is_once_schedule(workflow.schedule_cron)
        and previous_cron == workflow.schedule_cron
        and previous_tz == workflow.timezone
        and previous_next is None
        and not workflow.is_paused
    )
    workflow.next_run_at = None if same_once else _next_run(
        workflow.schedule_cron, workflow.timezone, workflow.is_paused
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A workflow with this name already exists.") from exc
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="workflow.updated",
        recon_id=workflow.recon_id,
        entity_type="workflow",
        entity_id=str(workflow.id),
        detail=body.model_dump(exclude_unset=True, exclude_none=True),
    )
    await db.commit()
    return _to_read(await _reload(db, workflow.id))


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    workflow = await get_accessible_workflow(db, current_user, workflow_id)
    workflow.deleted_at = datetime.now(UTC)
    workflow.next_run_at = None
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="workflow.deleted",
        recon_id=workflow.recon_id,
        entity_type="workflow",
        entity_id=str(workflow.id),
        detail={"name": workflow.name},
    )
    await db.commit()


@router.post("/{workflow_id}/runs", response_model=WorkflowRunRead, status_code=201)
async def trigger_workflow(
    workflow_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> WorkflowRunRead:
    workflow = await get_accessible_workflow(db, current_user, workflow_id)
    run = await queue_workflow_run(
        db, workflow, current_user, trigger_kind=WorkflowTriggerKind.MANUAL
    )
    if settings.environment == "local":
        await run_workflow(run.id)
    else:
        dispatch_run(run.id)
    return run_to_read(await reload_run(db, run.id))


@router.get("/{workflow_id}/runs", response_model=list[WorkflowRunRead])
async def list_workflow_runs(
    workflow_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[WorkflowRunRead]:
    await get_accessible_workflow(db, current_user, workflow_id)
    total = (
        await db.execute(
            select(func.count())
            .select_from(WorkflowRun)
            .where(WorkflowRun.workflow_id == workflow_id)
        )
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    stmt = (
        select(WorkflowRun)
        .options(
            selectinload(WorkflowRun.triggered_by),
            selectinload(WorkflowRun.steps),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.recon),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.created_by),
        )
        .where(WorkflowRun.workflow_id == workflow_id)
        .order_by(WorkflowRun.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    return [run_to_read(r) for r in (await db.execute(stmt)).unique().scalars().all()]


@runs_router.get("", response_model=list[WorkflowRunRead])
async def list_all_runs(
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[WorkflowRunRead]:
    stmt = (
        select(WorkflowRun)
        .options(
            selectinload(WorkflowRun.triggered_by),
            selectinload(WorkflowRun.steps),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.recon),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.created_by),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.recon).selectinload(Recon.owner),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.recon).selectinload(Recon.groups),
        )
        .join(Workflow)
        .where(Workflow.deleted_at.is_(None))
        .order_by(WorkflowRun.created_at.desc())
    )
    rows = list((await db.execute(stmt)).unique().scalars().all())
    visible = [r for r in rows if await can_manage_recon(db, current_user, r.workflow.recon)]
    response.headers["X-Total-Count"] = str(len(visible))
    start = pagination["offset"]
    end = start + pagination["page_size"]
    return [run_to_read(r) for r in visible[start:end]]


@runs_router.get("/{run_id}", response_model=WorkflowRunRead)
async def get_run(
    run_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> WorkflowRunRead:
    return run_to_read(await get_accessible_run(db, current_user, run_id))
