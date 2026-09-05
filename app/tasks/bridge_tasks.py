"""Bridge Members' Celery task — the old backend's `run_bridge`
(`views.py`), confirmed as the one genuinely long-running action in
`bridge_members` (it walks every imported row, unlike the fast
CRUD/default/import operations in bridge_mappings.py).

For each `ImportedRow`, every non-AMOUNT dimension's value is resolved
through that app's `BridgeMapping` crosswalk; a row is flagged
`kickout` if any dimension has no mapping at all, or maps to the old
backend's `"kickout"` sentinel (see app/models/bridge.py's module
docstring). Progress is published on the existing WebSocket scaffold
(`app/ws/`) — `bridge_run:{run_id}` — every 500 rows and once on
completion/failure, reusing the Redis pub/sub fan-out that scaffold
already provides rather than building a second progress-reporting path.

Uses `celery_session_scope()`, not `session_scope()` — see Phase 5's
KT (KT_PHASE5.md) and app/db/session.py for the event-loop bug that
distinction fixes.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update

from app.core.audit import record_audit_log
from app.db.session import celery_session_scope
from app.models.bridge import BridgeRun, BridgeRunStatus
from app.models.import_run import ImportedRow
from app.services.bridge_resolve import (
    load_bridged_dimensions,
    mapping_lookup_for_recon,
    resolve_imported_row,
)
from app.tasks.celery_app import celery_app
from app.ws.connection_manager import manager

logger = structlog.get_logger(__name__)

_PROGRESS_INTERVAL = 500


async def _broadcast(run_id: uuid.UUID, message: dict[str, object]) -> None:
    try:
        await manager.broadcast(f"bridge_run:{run_id}", message)
    except Exception:
        # Progress push is best-effort — a Redis hiccup must not fail the
        # actual computation. The run's own status row (polled via
        # GET .../bridge-runs/{id}) is always the source of truth.
        logger.warning("bridge_run_broadcast_failed", run_id=str(run_id))


async def _run_bridge(bridge_run_id: uuid.UUID) -> None:
    async with celery_session_scope() as db:
        run = (
            await db.execute(select(BridgeRun).where(BridgeRun.id == bridge_run_id))
        ).scalar_one()
        run.status = BridgeRunStatus.PROCESSING
        run.started_at = datetime.now(UTC)
        await db.flush()
        await _broadcast(run.id, {"status": "processing", "processed": 0, "total": None})

        try:
            dim_names = await load_bridged_dimensions(db, run.recon_id)
            lookup = await mapping_lookup_for_recon(db, run.recon_id)

            rows = (
                await db.execute(
                    select(ImportedRow.id, ImportedRow.app_number, ImportedRow.data).where(
                        ImportedRow.recon_id == run.recon_id
                    )
                )
            ).all()

            total = len(rows)
            run.total_rows = total
            await db.flush()

            kickout_count = 0
            updates: list[dict[str, object]] = []
            for processed, row in enumerate(rows, start=1):
                resolved = resolve_imported_row(
                    app_number=row.app_number,
                    data=row.data,
                    dim_names=dim_names,
                    lookup=lookup,
                )
                is_kickout = resolved.kickout
                if is_kickout:
                    kickout_count += 1
                updates.append({"id": row.id, "kickout": is_kickout})

                if processed % _PROGRESS_INTERVAL == 0 or processed == total:
                    run.processed_rows = processed
                    await db.flush()
                    await _broadcast(
                        run.id, {"status": "processing", "processed": processed, "total": total}
                    )

            if updates:
                # SQLAlchemy 2.0's "ORM Bulk UPDATE by Primary Key": a bare
                # `update(Entity)` (no `.where()`) plus a list of dicts
                # keyed by the entity's actual PK attribute name (`id`)
                # auto-batches into an efficient multi-row UPDATE. Found the
                # correct form live — an explicit `.where(ImportedRow.id ==
                # bindparam(...))` looks equivalent but SQLAlchemy rejects it
                # ("No primary key value supplied") because that's a
                # different code path expecting a *named* bindparam matching
                # the WHERE clause, not this by-PK batch form.
                # synchronize_session=None: no loaded ImportedRow objects are
                # read again after this point in the task, so there's no
                # stale in-memory state to reconcile against skipping it —
                # required explicitly by 2.0 for this bulk form regardless.
                await db.execute(
                    update(ImportedRow), updates, execution_options={"synchronize_session": None}
                )

            run.status = BridgeRunStatus.COMPLETED
            run.kickout_count = kickout_count
            run.completed_at = datetime.now(UTC)
            await db.flush()
            await record_audit_log(
                db,
                actor_user_id=run.created_by_id,
                action="bridge_run.completed",
                recon_id=run.recon_id,
                entity_type="bridge_run",
                entity_id=str(run.id),
                detail={"total_rows": str(total), "kickout_count": str(kickout_count)},
            )
            await _broadcast(
                run.id,
                {
                    "status": "completed",
                    "processed": total,
                    "total": total,
                    "kickout_count": kickout_count,
                },
            )

        except Exception:
            logger.exception("bridge_run_failed_unexpectedly", bridge_run_id=str(bridge_run_id))
            run.status = BridgeRunStatus.FAILED
            run.error_message = "An unexpected error occurred while computing this bridge run."
            run.completed_at = datetime.now(UTC)
            await _broadcast(run.id, {"status": "failed", "error": run.error_message})


@celery_app.task(name="run_bridge_task")  # type: ignore[untyped-decorator]
def run_bridge_task(bridge_run_id: str) -> None:
    asyncio.run(_run_bridge(uuid.UUID(bridge_run_id)))
