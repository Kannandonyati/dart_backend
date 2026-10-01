"""Start a queued workflow run in this process (local) or on Celery."""

from __future__ import annotations

import asyncio
import uuid

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


def dispatch_run(run_id: uuid.UUID) -> None:
    """Local uvicorn has no Beat/worker, so the API process runs the graph."""
    if settings.environment == "local":
        asyncio.create_task(_run_local(run_id))
        return
    from app.tasks.workflow_tasks import run_workflow_task

    run_workflow_task.delay(str(run_id))


async def _run_local(run_id: uuid.UUID) -> None:
    from app.services.workflow_runner import run_workflow

    try:
        await run_workflow(run_id)
    except Exception:
        logger.exception("workflow_run_local_failed", run_id=str(run_id))


async def run_workflow_clock() -> None:
    from app.tasks.workflow_tasks import enqueue_due_workflows

    await asyncio.sleep(2)
    while True:
        try:
            queued = await enqueue_due_workflows()
            if queued:
                logger.info("workflow_clock_queued", count=queued)
        except Exception:
            logger.exception("workflow_clock_failed")
        await asyncio.sleep(15)
