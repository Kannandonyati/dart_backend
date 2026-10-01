"""Start an import run in this process (local) or on Celery."""

from __future__ import annotations

import uuid

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


async def dispatch_import(run_id: uuid.UUID) -> None:
    """Local uvicorn has no worker, so parse the file in this process.

    Await it on the upload request so the recon page does not show a
    finished upload while workflow import nodes still see no rows.
    """
    if settings.environment == "local":
        from app.tasks.import_tasks import _run_import

        try:
            await _run_import(run_id)
        except Exception:
            logger.exception("import_run_local_failed", run_id=str(run_id))
        return
    from app.tasks.import_tasks import run_import_task

    run_import_task.delay(str(run_id))
