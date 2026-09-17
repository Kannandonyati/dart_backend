"""Run Import — file upload (enqueues a Celery task), history, status
polling, reading back imported rows, and CSV/ZIP export. Access follows
the recon they belong to — see app/core/recon_access.py.

Upload is asynchronous by design (a real improvement over the old
backend, which blocked the HTTP request for the entire validate-and-
load — see app/tasks/import_tasks.py's docstring): this endpoint does
only the cheap parts synchronously (recon/app validation, saving the
file, creating a `pending` ImportRun) and returns immediately: the
Celery task does the actual (potentially slow, at real file-size scale)
validation and bulk insert. Callers poll `GET .../imports/{id}` for
status.

Route order: `/data` and `/export` are registered before
`/{import_run_id}` — same reason as every prior phase's
literal-before-parameterized routes.
"""

import csv
import io
import uuid
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.audit import record_audit_log
from app.core.exceptions import AppError, NotFoundError
from app.core.recon_access import get_accessible_recon
from app.models.dimension import ReconApp
from app.models.import_run import ImportedRow, ImportRun
from app.schemas.import_run import ImportedRowRead, ImportRunRead
from app.services.file_storage import save_upload_async
from app.tasks.import_tasks import run_import_task

router = APIRouter(prefix="/recons/{recon_id}/imports", tags=["run-import"])

_PREFERRED_COLUMNS = ("YEAR", "PERIOD", "AMOUNT")


def _to_read(run: ImportRun) -> ImportRunRead:
    return ImportRunRead(
        id=run.id,
        recon_id=run.recon_id,
        app_number=run.app_number,
        file_name=run.file_name,
        status=run.status,
        row_count=run.row_count,
        error_message=run.error_message,
        created_by=run.created_by.username,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


def _set_total_count(response: Response, total: int) -> None:
    response.headers["X-Total-Count"] = str(total)


def _csv_columns(rows: list[ImportedRow]) -> list[str]:
    present: set[str] = set()
    for row in rows:
        present.update(row.data.keys())
    columns = [name for name in _PREFERRED_COLUMNS if name in present]
    columns.extend(sorted(name for name in present if name not in _PREFERRED_COLUMNS))
    return columns


def _rows_to_csv(rows: list[ImportedRow]) -> bytes:
    columns = _csv_columns(rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.data.get(column, "") for column in columns])
    return buffer.getvalue().encode("utf-8-sig")


@router.post("", response_model=ImportRunRead, status_code=201)
async def upload_import_file(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    app_number: Annotated[int, Form()],
    file: UploadFile,
) -> ImportRunRead:
    await get_accessible_recon(db, current_user, recon_id)

    app_exists = (
        await db.execute(
            select(ReconApp.id).where(
                ReconApp.recon_id == recon_id, ReconApp.app_number == app_number
            )
        )
    ).scalar_one_or_none()
    if app_exists is None:
        raise NotFoundError(f"App {app_number} is not configured for this recon.")

    if not file.filename:
        raise AppError("A file name is required.", code="missing_filename")

    content = await file.read()
    stored_path = await save_upload_async(content)

    run = ImportRun(
        recon_id=recon_id,
        app_number=app_number,
        file_name=file.filename,
        file_path=stored_path,
        created_by_id=current_user.id,
    )
    db.add(run)
    await db.flush()
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="import.uploaded",
        recon_id=recon_id,
        entity_type="import_run",
        entity_id=str(run.id),
        detail={"file_name": file.filename, "app_number": str(app_number)},
    )
    await db.commit()

    run_import_task.delay(str(run.id))

    stmt = (
        select(ImportRun).options(selectinload(ImportRun.created_by)).where(ImportRun.id == run.id)
    )
    run = (await db.execute(stmt)).scalar_one()
    return _to_read(run)


@router.get("", response_model=list[ImportRunRead])
async def list_import_runs(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[ImportRunRead]:
    await get_accessible_recon(db, current_user, recon_id)
    total = (
        await db.execute(
            select(func.count()).select_from(ImportRun).where(ImportRun.recon_id == recon_id)
        )
    ).scalar_one()
    _set_total_count(response, total)
    stmt = (
        select(ImportRun)
        .options(selectinload(ImportRun.created_by))
        .where(ImportRun.recon_id == recon_id)
        .order_by(ImportRun.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    result = await db.execute(stmt)
    return [_to_read(r) for r in result.scalars().all()]


@router.get("/data", response_model=list[ImportedRowRead])
async def list_imported_data(
    recon_id: uuid.UUID,
    app_number: int,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> list[ImportedRowRead]:
    await get_accessible_recon(db, current_user, recon_id)
    filters = (ImportedRow.recon_id == recon_id, ImportedRow.app_number == app_number)
    total = (
        await db.execute(select(func.count()).select_from(ImportedRow).where(*filters))
    ).scalar_one()
    _set_total_count(response, total)
    stmt = (
        select(ImportedRow)
        .where(*filters)
        .order_by(ImportedRow.created_at, ImportedRow.row_number)
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    result = await db.execute(stmt)
    return [
        ImportedRowRead(id=r.id, row_number=r.row_number, data=r.data, kickout=r.kickout)
        for r in result.scalars().all()
    ]


@router.get("/export")
async def export_imported_data(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    app_number: int | None = None,
) -> StreamingResponse:
    """Old DART's POST /run_import/export — a ZIP of per-app CSVs, or a
    single CSV when `app_number` is given. Streams every imported row,
    not the UI page limit."""
    await get_accessible_recon(db, current_user, recon_id)

    apps = (
        (
            await db.execute(
                select(ReconApp)
                .where(ReconApp.recon_id == recon_id)
                .order_by(ReconApp.app_number)
            )
        )
        .scalars()
        .all()
    )
    if app_number is not None:
        apps = [app for app in apps if app.app_number == app_number]
        if not apps:
            raise NotFoundError(f"App {app_number} is not configured for this recon.")

    per_app_rows: list[tuple[ReconApp, list[ImportedRow]]] = []
    for app in apps:
        rows = (
            (
                await db.execute(
                    select(ImportedRow)
                    .where(
                        ImportedRow.recon_id == recon_id,
                        ImportedRow.app_number == app.app_number,
                    )
                    .order_by(ImportedRow.created_at, ImportedRow.row_number)
                )
            )
            .scalars()
            .all()
        )
        per_app_rows.append((app, list(rows)))

    if app_number is not None:
        _app, rows = per_app_rows[0]
        body = _rows_to_csv(rows)
        filename = f"{_app.name or f'App_{_app.app_number}'}.csv"
        return StreamingResponse(
            iter([body]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for app, rows in per_app_rows:
            folder = app.name or f"App_{app.app_number}"
            archive.writestr(f"{folder}/{folder}.csv", _rows_to_csv(rows))
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="Source_Data_Export.zip"',
        },
    )


@router.get("/{import_run_id}", response_model=ImportRunRead)
async def get_import_run(
    recon_id: uuid.UUID, import_run_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> ImportRunRead:
    await get_accessible_recon(db, current_user, recon_id)
    stmt = (
        select(ImportRun)
        .options(selectinload(ImportRun.created_by))
        .where(ImportRun.id == import_run_id, ImportRun.recon_id == recon_id)
    )
    run = (await db.execute(stmt)).scalar_one_or_none()
    if run is None:
        raise NotFoundError("Import run not found")
    return _to_read(run)
