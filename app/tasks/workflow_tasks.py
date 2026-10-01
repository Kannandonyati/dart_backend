"""Celery entry points for scheduled and manual workflow runs."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictError
from app.db.session import celery_session_scope
from app.models.user import User
from app.models.workflow import Workflow, WorkflowRun, WorkflowRunStatus, WorkflowTriggerKind
from app.services.workflow_dispatch import dispatch_run
from app.services.workflow_queue import queue_workflow_run
from app.services.workflow_runner import run_workflow
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="run_workflow_task")  # type: ignore[untyped-decorator]
def run_workflow_task(run_id: str) -> None:
    asyncio.run(run_workflow(uuid.UUID(run_id)))


async def _queued_run_ids(workflow_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    async with celery_session_scope() as db:
        stmt = select(WorkflowRun.id).where(WorkflowRun.status == WorkflowRunStatus.QUEUED)
        if workflow_id is not None:
            stmt = stmt.where(WorkflowRun.workflow_id == workflow_id)
        return list((await db.execute(stmt)).scalars().all())


async def enqueue_due_workflows() -> int:
    """Queue every unpaused workflow whose next_run_at is due.

    One Beat tick owns scheduling. A second process (old Airflow minute
    DAG plus Django auto-load) is exactly the dual-scheduler bug this
    replaces. Duplicate in-flight runs are rejected by the partial unique
    index on workflow_runs.
    """
    started = 0
    for run_id in await _queued_run_ids():
        dispatch_run(run_id)
        started += 1
    now = datetime.now(UTC)
    async with celery_session_scope() as db:
        due = list(
            (
                await db.execute(
                    select(Workflow)
                    .options(selectinload(Workflow.created_by))
                    .where(
                        Workflow.deleted_at.is_(None),
                        Workflow.is_paused.is_(False),
                        Workflow.schedule_cron.is_not(None),
                        Workflow.next_run_at.is_not(None),
                        Workflow.next_run_at <= now,
                    )
                )
            )
            .scalars()
            .all()
        )
        ids = [(workflow, workflow.created_by) for workflow in due]

    for workflow, creator in ids:
        try:
            async with celery_session_scope() as db:
                loaded = (
                    await db.execute(
                        select(Workflow)
                        .options(selectinload(Workflow.created_by))
                        .where(Workflow.id == workflow.id)
                    )
                ).scalar_one()
                user = (
                    await db.execute(select(User).where(User.id == creator.id))
                ).scalar_one()
                run = await queue_workflow_run(
                    db, loaded, user, trigger_kind=WorkflowTriggerKind.SCHEDULE
                )
            dispatch_run(run.id)
            started += 1
        except ConflictError:
            for run_id in await _queued_run_ids(workflow.id):
                dispatch_run(run_id)
                started += 1
        except Exception:
            logger.warning(
                "schedule_enqueue_skipped",
                workflow_id=str(workflow.id),
                exc_info=True,
            )
    return started


@celery_app.task(name="tick_due_workflows")  # type: ignore[untyped-decorator]
def tick_due_workflows() -> int:
    return asyncio.run(enqueue_due_workflows())
