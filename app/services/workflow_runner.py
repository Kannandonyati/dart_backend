"""Execute one queued workflow run against in-process recon services."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import record_audit_log
from app.core.config import settings
from app.core.exceptions import AppError
from app.db.session import celery_session_scope, session_scope
from app.models.bridge import BridgeMapping, BridgeRun, BridgeRunStatus
from app.models.dimension import Dimension
from app.models.import_run import ImportedRow, ImportRun, ImportStatus
from app.models.recon import Recon
from app.models.workflow import (
    Workflow,
    WorkflowRun,
    WorkflowRunStatus,
    WorkflowRunStep,
    WorkflowRunStepStatus,
)
from app.services.report_run import compute_report
from app.services.sync_run import run_transformation_page
from app.services.workflow_schedule import is_once_schedule, next_scheduled_at
from app.tasks.bridge_tasks import _run_bridge
from app.tasks.import_tasks import _run_import
from app.ws.connection_manager import manager

logger = structlog.get_logger(__name__)


async def _broadcast(run_id: uuid.UUID, message: dict[str, object]) -> None:
    try:
        await manager.broadcast(f"workflow_run:{run_id}", message)
    except Exception:
        logger.warning("workflow_run_broadcast_failed", run_id=str(run_id))


async def _step_bridge(
    db: AsyncSession, workflow: Workflow, user_id: uuid.UUID
) -> dict[str, str]:
    run = BridgeRun(recon_id=workflow.recon_id, created_by_id=user_id)
    db.add(run)
    await db.commit()
    await _run_bridge(run.id)
    loaded = (
        await db.execute(select(BridgeRun).where(BridgeRun.id == run.id))
    ).scalar_one()
    if loaded.status == BridgeRunStatus.FAILED:
        raise AppError(loaded.error_message or "Bridge run failed.", code="bridge_failed")
    return {
        "bridge_run_id": str(loaded.id),
        "kickout_count": str(loaded.kickout_count or 0),
        "total_rows": str(loaded.total_rows or 0),
    }


async def _step_kickouts(
    db: AsyncSession, recon_id: uuid.UUID, step: dict[str, object]
) -> dict[str, str]:
    latest = (
        await db.execute(
            select(BridgeRun)
            .where(BridgeRun.recon_id == recon_id, BridgeRun.status == BridgeRunStatus.COMPLETED)
            .order_by(BridgeRun.completed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        raise AppError("Bridge has not been run for this recon.", code="bridge_missing")
    count = latest.kickout_count or 0
    raw_ignore = step.get("ignore_kickout", False)
    if isinstance(raw_ignore, str):
        ignore = raw_ignore.lower() in {"true", "1", "yes"}
    else:
        ignore = bool(raw_ignore)
    try:
        tolerance = int(step.get("kickout_tolerance") or 0)
    except (TypeError, ValueError):
        tolerance = 0
    if not ignore and count > tolerance:
        raise AppError(
            f"Workflow stopped: {count} kickout(s) remain.",
            code="kickouts_open",
        )
    return {"kickout_count": str(count), "ignored": "true" if ignore else "false"}


def _app_number_from_step(step: dict[str, Any]) -> int | None:
    raw = step.get("app_number")
    if raw not in (None, ""):
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    key = str(step.get("key") or "")
    if key.startswith("import_app_data_"):
        suffix = key.removeprefix("import_app_data_")
        if suffix.isdigit():
            return int(suffix)
    return None


async def _drain_pending_imports(
    recon_id: uuid.UUID, app_number: int | None
) -> int:
    async with session_scope() as db:
        params: dict[str, object] = {"recon_id": recon_id}
        sql = """
            select id from import_runs
            where recon_id = :recon_id
              and status = CAST(:pending AS import_status)
        """
        params["pending"] = ImportStatus.PENDING.name
        if app_number is not None:
            sql += " and app_number = :app_number"
            params["app_number"] = app_number
        ids = list((await db.execute(text(sql), params)).scalars().all())
    for import_id in ids:
        await _run_import(import_id)
    return len(ids)


async def _stamp_import_history(
    *,
    recon_id: uuid.UUID,
    app_number: int,
    user_id: uuid.UUID,
    row_count: int,
) -> None:
    """Commit a history row on the API engine so GET /imports sees it
    even if the workflow's throwaway Celery session later rolls back."""
    async with session_scope() as db:
        source = (
            await db.execute(
                select(ImportRun)
                .where(
                    ImportRun.recon_id == recon_id,
                    ImportRun.app_number == app_number,
                    ImportRun.status == ImportStatus.COMPLETED,
                )
                .order_by(ImportRun.completed_at.desc().nulls_last(), ImportRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        run_id = uuid.uuid4()
        await db.execute(
            insert(ImportRun).values(
                id=run_id,
                recon_id=recon_id,
                app_number=app_number,
                file_name=source.file_name if source else f"App {app_number}.csv",
                file_path="workflow-replay",
                status=ImportStatus.COMPLETED,
                row_count=row_count,
                created_by_id=user_id,
                started_at=now,
                completed_at=now,
            )
        )
        await record_audit_log(
            db,
            actor_user_id=user_id,
            action="import.workflow",
            recon_id=recon_id,
            entity_type="import_run",
            entity_id=str(run_id),
            detail={"app_number": str(app_number), "row_count": str(row_count)},
        )
    logger.info(
        "import_history_stamped",
        recon_id=str(recon_id),
        app_number=app_number,
        row_count=row_count,
        import_run_id=str(run_id),
    )


async def _step_import_apps(
    db: AsyncSession,
    recon_id: uuid.UUID,
    step: dict[str, Any],
    user_id: uuid.UUID,
) -> dict[str, str]:
    app_number = _app_number_from_step(step)
    await _drain_pending_imports(recon_id, app_number)
    row_stmt = select(func.count()).select_from(ImportedRow).where(
        ImportedRow.recon_id == recon_id,
        ImportedRow.deleted_flag.is_(False),
    )
    run_stmt = (
        select(ImportRun)
        .where(ImportRun.recon_id == recon_id)
        .order_by(ImportRun.created_at.desc())
    )
    if app_number is not None:
        row_stmt = row_stmt.where(ImportedRow.app_number == app_number)
        run_stmt = run_stmt.where(ImportRun.app_number == app_number)
    total = int((await db.execute(row_stmt)).scalar_one() or 0)
    latest = (await db.execute(run_stmt.limit(1))).scalar_one_or_none()
    label = step.get("app_name") or (f"App {app_number}" if app_number else "this recon")
    if latest is not None and latest.status == ImportStatus.FAILED and total == 0:
        raise AppError(
            latest.error_message or f"Import failed for {label}.",
            code="import_failed",
        )
    if total == 0:
        raise AppError(
            f"No app data has been imported for {label}.",
            code="import_missing",
        )
    if app_number is not None:
        await _stamp_import_history(
            recon_id=recon_id,
            app_number=app_number,
            user_id=user_id,
            row_count=total,
        )
    else:
        apps = (
            await db.execute(
                select(ImportedRow.app_number)
                .where(
                    ImportedRow.recon_id == recon_id,
                    ImportedRow.deleted_flag.is_(False),
                )
                .distinct()
            )
        ).scalars().all()
        for number in apps:
            app_total = int(
                (
                    await db.execute(
                        select(func.count())
                        .select_from(ImportedRow)
                        .where(
                            ImportedRow.recon_id == recon_id,
                            ImportedRow.app_number == number,
                            ImportedRow.deleted_flag.is_(False),
                        )
                    )
                ).scalar_one()
                or 0
            )
            await _stamp_import_history(
                recon_id=recon_id,
                app_number=int(number),
                user_id=user_id,
                row_count=app_total,
            )
    files = (
        await db.execute(
            select(func.count())
            .select_from(ImportRun)
            .where(
                ImportRun.recon_id == recon_id,
                ImportRun.status == ImportStatus.COMPLETED,
                *([ImportRun.app_number == app_number] if app_number is not None else []),
            )
        )
    ).scalar_one()
    return {
        "file_count": str(int(files or 0)),
        "app_count": "1" if app_number is not None else "0",
        "row_count": str(total),
        "app_number": str(app_number or ""),
    }


async def _step_import_bridge(db: AsyncSession, recon_id: uuid.UUID) -> dict[str, str]:
    count = (
        await db.execute(
            select(func.count())
            .select_from(BridgeMapping)
            .where(BridgeMapping.recon_id == recon_id)
        )
    ).scalar_one()
    if not count:
        raise AppError(
            "No bridge members have been imported for this recon.",
            code="bridge_import_missing",
        )
    return {"member_count": str(count)}


async def _step_upload_dimensions(db: AsyncSession, recon_id: uuid.UUID) -> dict[str, str]:
    count = (
        await db.execute(
            select(func.count()).select_from(Dimension).where(Dimension.recon_id == recon_id)
        )
    ).scalar_one()
    if not count:
        raise AppError("No dimensions on this recon.", code="dimensions_missing")
    return {"dimension_count": str(count)}


async def _execute_step(
    db: AsyncSession, workflow: Workflow, step: dict[str, Any], user_id: uuid.UUID
) -> dict[str, str]:
    stype = step["type"]
    if stype == "import_app_data":
        return await _step_import_apps(db, workflow.recon_id, step, user_id)
    if stype == "import_bridge_data":
        return await _step_import_bridge(db, workflow.recon_id)
    if stype == "upload_dimensions":
        return await _step_upload_dimensions(db, workflow.recon_id)
    if stype == "run_bridge":
        return await _step_bridge(db, workflow, user_id)
    if stype == "check_kickouts":
        return await _step_kickouts(db, workflow.recon_id, step)
    if stype == "run_transformation":
        _, total = await run_transformation_page(
            db, workflow.recon_id, offset=0, page_size=1, app_number=None
        )
        return {"row_count": str(total)}
    if stype == "run_report":
        result = await compute_report(
            db,
            workflow.recon_id,
            variance_threshold=Decimal("0"),
            filter_criteria=None,
        )
        return {"row_count": str(result.summary.total_rows)}
    raise AppError(f"Unknown workflow step type '{stype}'.", code="invalid_step_type")


async def _advance_schedule(db: AsyncSession, workflow: Workflow) -> None:
    if is_once_schedule(workflow.schedule_cron):
        workflow.next_run_at = None
        return
    if not workflow.schedule_cron or workflow.is_paused:
        workflow.next_run_at = None
        return
    workflow.next_run_at = next_scheduled_at(
        workflow.schedule_cron, workflow.timezone, datetime.now(UTC)
    )


async def _touch_recon(db: AsyncSession, recon_id: uuid.UUID) -> None:
    await db.execute(
        update(Recon).where(Recon.id == recon_id).values(updated_at=datetime.now(UTC))
    )


async def run_workflow(run_id: uuid.UUID) -> None:
    scope = session_scope if settings.environment == "local" else celery_session_scope
    async with scope() as db:
        run = (
            await db.execute(
                select(WorkflowRun)
                .options(selectinload(WorkflowRun.workflow), selectinload(WorkflowRun.steps))
                .where(WorkflowRun.id == run_id)
            )
        ).scalar_one_or_none()
        if run is None or run.status != WorkflowRunStatus.QUEUED:
            return
        workflow = run.workflow
        run.status = WorkflowRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        await db.flush()
        await _broadcast(run.id, {"status": "running", "current_step": None})

        try:
            steps = list(workflow.definition.get("steps") or [])
            for spec in steps:
                row = WorkflowRunStep(
                    run_id=run.id,
                    step_key=spec["key"],
                    step_type=spec["type"],
                    status=WorkflowRunStepStatus.RUNNING,
                    started_at=datetime.now(UTC),
                )
                db.add(row)
                run.current_step = spec["key"]
                await db.flush()
                await _broadcast(
                    run.id,
                    {
                        "status": "running",
                        "current_step": spec["key"],
                        "step_type": spec["type"],
                    },
                )
                try:
                    detail = await _execute_step(db, workflow, spec, run.triggered_by_id)
                except AppError as exc:
                    row.status = WorkflowRunStepStatus.FAILED
                    row.error_message = exc.message
                    row.completed_at = datetime.now(UTC)
                    run.status = WorkflowRunStatus.FAILED
                    run.error_message = exc.message
                    run.completed_at = datetime.now(UTC)
                    await _advance_schedule(db, workflow)
                    await _touch_recon(db, workflow.recon_id)
                    await _broadcast(
                        run.id,
                        {
                            "status": "failed",
                            "current_step": spec["key"],
                            "error": exc.message,
                        },
                    )
                    return
                row.status = WorkflowRunStepStatus.SUCCEEDED
                row.detail = detail
                row.completed_at = datetime.now(UTC)
                await _broadcast(
                    run.id,
                    {
                        "status": "running",
                        "current_step": spec["key"],
                        "step_type": spec["type"],
                        "detail": detail,
                    },
                )

            run.status = WorkflowRunStatus.SUCCEEDED
            run.current_step = None
            run.completed_at = datetime.now(UTC)
            await _advance_schedule(db, workflow)
            await _touch_recon(db, workflow.recon_id)
            await _broadcast(run.id, {"status": "succeeded"})
        except Exception:
            logger.exception("workflow_run_failed_unexpectedly", run_id=str(run_id))
            run.status = WorkflowRunStatus.FAILED
            run.error_message = "An unexpected error occurred while running this workflow."
            run.completed_at = datetime.now(UTC)
            await _touch_recon(db, workflow.recon_id)
            await _broadcast(run.id, {"status": "failed", "error": run.error_message})
