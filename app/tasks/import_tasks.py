"""Run Import's Celery task — the first real task in this codebase
(see celery_app.py's docstring: `example_task.py` existed purely to
prove the worker/broker/backend wiring before there was real work to
queue; this replaces it).

The old backend's `run_import/upload` does this same validate-then-load
work synchronously, inside the HTTP request (confirmed in its
`views.py` — no job/status table, no background mechanism at all).
Moving it to Celery is a genuine architectural improvement this phase
makes, not a port of existing async behavior — see KT_PHASE5.md.

Celery tasks in this codebase are sync functions that drive the async
DB session via `asyncio.run` + `session_scope` (see app/db/session.py's
docstring: `session_scope` is explicitly for "Celery tasks, startup
scripts, one-off maintenance code").
"""

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import selectinload

from app.db.session import celery_session_scope
from app.models.dimension import Dimension, ReconApp
from app.models.import_run import ImportedRow, ImportRun, ImportStatus
from app.services.file_storage import delete_upload, read_upload
from app.services.import_validation import (
    DimensionForValidation,
    ImportValidationError,
    validate_and_parse,
)
from app.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


async def _run_import(import_run_id: uuid.UUID) -> None:
    async with celery_session_scope() as db:
        run = (
            await db.execute(select(ImportRun).where(ImportRun.id == import_run_id))
        ).scalar_one()
        run.status = ImportStatus.PROCESSING
        run.started_at = datetime.now(UTC)
        await db.flush()

        try:
            app_settings = (
                await db.execute(
                    select(ReconApp).where(
                        ReconApp.recon_id == run.recon_id, ReconApp.app_number == run.app_number
                    )
                )
            ).scalar_one()

            dim_rows = (
                (
                    await db.execute(
                        select(Dimension)
                        .options(selectinload(Dimension.mappings))
                        .where(Dimension.recon_id == run.recon_id)
                        .order_by(Dimension.position)
                    )
                )
                .scalars()
                .all()
            )
            dimensions = [
                DimensionForValidation(
                    name=d.name,
                    in_file=m.in_file,
                    column_location=m.column_location,
                    default_value=m.default_value,
                )
                for d in dim_rows
                for m in d.mappings
                if m.app_number == run.app_number
            ]

            raw = read_upload(run.file_path)
            parsed_rows = validate_and_parse(
                raw,
                delimiter=app_settings.delimiter,
                has_header=app_settings.has_header,
                dimensions=dimensions,
            )

            # Replace this app's live rows only after the file has fully
            # validated. A failed re-import must not wipe good data; a
            # successful one must not append (re-uploading 45 rows would
            # otherwise show 90). Other apps on the same recon are left
            # alone. ImportRun history is unchanged.
            await db.execute(
                delete(ImportedRow).where(
                    ImportedRow.recon_id == run.recon_id,
                    ImportedRow.app_number == run.app_number,
                )
            )

            if parsed_rows:
                await db.execute(
                    insert(ImportedRow),
                    [
                        {
                            "id": uuid.uuid4(),
                            "import_run_id": run.id,
                            "recon_id": run.recon_id,
                            "app_number": run.app_number,
                            "row_number": i + 1,
                            "data": row,
                        }
                        for i, row in enumerate(parsed_rows)
                    ],
                )

            run.status = ImportStatus.COMPLETED
            run.row_count = len(parsed_rows)
            run.completed_at = datetime.now(UTC)

        except ImportValidationError as exc:
            run.status = ImportStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = datetime.now(UTC)
        except Exception:
            logger.exception("import_run_failed_unexpectedly", import_run_id=str(import_run_id))
            run.status = ImportStatus.FAILED
            run.error_message = "An unexpected error occurred while processing this file."
            run.completed_at = datetime.now(UTC)
        finally:
            delete_upload(run.file_path)


@celery_app.task(name="run_import_task")  # type: ignore[untyped-decorator]
def run_import_task(import_run_id: str) -> None:
    asyncio.run(_run_import(uuid.UUID(import_run_id)))
