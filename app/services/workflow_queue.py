"""Create a queued workflow run and enqueue the Celery orchestrator."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import ConflictError
from app.models.user import User
from app.models.workflow import Workflow, WorkflowRun, WorkflowRunStatus, WorkflowTriggerKind
from app.schemas.workflow import WorkflowRunRead, WorkflowRunStepRead


def run_to_read(run: WorkflowRun) -> WorkflowRunRead:
    steps = sorted(
        run.steps,
        key=lambda step: (step.started_at is None, step.started_at or step.step_key),
    )
    return WorkflowRunRead(
        id=run.id,
        workflow_id=run.workflow_id,
        workflow_name=run.workflow.name,
        recon_id=run.workflow.recon_id,
        status=run.status,
        trigger_kind=run.trigger_kind,
        triggered_by=run.triggered_by.username,
        current_step=run.current_step,
        error_message=run.error_message,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        steps=[
            WorkflowRunStepRead(
                id=step.id,
                step_key=step.step_key,
                step_type=step.step_type,
                status=step.status,
                attempt=step.attempt,
                detail=step.detail,
                error_message=step.error_message,
                started_at=step.started_at,
                completed_at=step.completed_at,
            )
            for step in steps
        ],
    )


async def queue_workflow_run(
    db: DbSession,
    workflow: Workflow,
    user: User,
    *,
    trigger_kind: WorkflowTriggerKind,
) -> WorkflowRun:
    existing = (
        await db.execute(
            select(WorkflowRun.id)
            .where(
                WorkflowRun.workflow_id == workflow.id,
                WorkflowRun.status.in_((WorkflowRunStatus.QUEUED, WorkflowRunStatus.RUNNING)),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("This workflow already has a run in progress.")

    run = WorkflowRun(
        workflow_id=workflow.id,
        triggered_by_id=user.id,
        trigger_kind=trigger_kind,
    )
    db.add(run)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("This workflow already has a run in progress.") from exc

    await record_audit_log(
        db,
        actor_user_id=user.id,
        action="workflow_run.queued",
        recon_id=workflow.recon_id,
        entity_type="workflow_run",
        entity_id=str(run.id),
        detail={"workflow_id": str(workflow.id), "trigger": trigger_kind.value},
    )
    await db.commit()
    return run


async def reload_run(db: DbSession, run_id: uuid.UUID) -> WorkflowRun:
    stmt = (
        select(WorkflowRun)
        .options(
            selectinload(WorkflowRun.triggered_by),
            selectinload(WorkflowRun.steps),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.created_by),
            selectinload(WorkflowRun.workflow),
        )
        .where(WorkflowRun.id == run_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()
