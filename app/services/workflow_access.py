"""Load a live workflow the caller can manage, or 404."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.core.exceptions import NotFoundError
from app.core.recon_access import can_manage_recon
from app.models.recon import Recon
from app.models.user import User
from app.models.workflow import Workflow, WorkflowRun


async def get_accessible_workflow(db: DbSession, user: User, workflow_id: uuid.UUID) -> Workflow:
    stmt = (
        select(Workflow)
        .options(
            selectinload(Workflow.recon).selectinload(Recon.owner),
            selectinload(Workflow.recon).selectinload(Recon.groups),
            selectinload(Workflow.created_by),
        )
        .where(Workflow.id == workflow_id, Workflow.deleted_at.is_(None))
    )
    workflow = (await db.execute(stmt)).scalar_one_or_none()
    if workflow is None or not await can_manage_recon(db, user, workflow.recon):
        raise NotFoundError("Workflow not found")
    return workflow


async def get_accessible_run(db: DbSession, user: User, run_id: uuid.UUID) -> WorkflowRun:
    stmt = (
        select(WorkflowRun)
        .options(
            selectinload(WorkflowRun.triggered_by),
            selectinload(WorkflowRun.steps),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.recon).selectinload(Recon.owner),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.recon).selectinload(Recon.groups),
            selectinload(WorkflowRun.workflow).selectinload(Workflow.created_by),
        )
        .where(WorkflowRun.id == run_id)
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None or not await can_manage_recon(db, user, run.workflow.recon):
        raise NotFoundError("Workflow run not found")
    return run
