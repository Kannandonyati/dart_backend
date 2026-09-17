"""Run Report HTTP surface — computation lives in `app.services.report_run`.

Matching uses bridge-resolved keys; amounts apply bridge then Transformation
`SyncMapping.flip_sign` (old dart-db `sign_reversed_amount`). Variance is
baseline − comparison (signed). Kickout rows are excluded.
"""

import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import NotFoundError
from app.core.recon_access import get_accessible_recon
from app.models.import_run import ImportRun
from app.models.report import ReportSignoff
from app.schemas.report import (
    LastRefreshRead,
    ReportRowRead,
    ReportRunResponse,
    SignoffRead,
    SignoffRequest,
)
from app.services.report_run import compute_report, resolve_filter_criteria

router = APIRouter(prefix="/recons/{recon_id}/report", tags=["run-report"])


async def _run(
    db: DbSession,
    recon_id: uuid.UUID,
    *,
    variance_threshold: Decimal,
    filter_id: uuid.UUID | None,
    baseline_app: int,
    comparison_app: int,
) -> ReportRunResponse:
    criteria = await resolve_filter_criteria(db, recon_id, filter_id)
    return await compute_report(
        db,
        recon_id,
        variance_threshold=variance_threshold,
        filter_criteria=criteria,
        baseline_app=baseline_app,
        comparison_app=comparison_app,
    )


@router.post("/run", response_model=ReportRunResponse)
async def run_report(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    variance_threshold: Decimal = Decimal("0"),
    filter_id: uuid.UUID | None = None,
    baseline_app: int = 1,
    comparison_app: int = 2,
) -> ReportRunResponse:
    await get_accessible_recon(db, current_user, recon_id)
    result = await _run(
        db,
        recon_id,
        variance_threshold=variance_threshold,
        filter_id=filter_id,
        baseline_app=baseline_app,
        comparison_app=comparison_app,
    )
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="report.run",
        recon_id=recon_id,
        entity_type="report",
        detail={"row_count": str(len(result.rows))},
    )
    await db.commit()
    return result


@router.get("/export")
async def export_report(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    variance_threshold: Decimal = Decimal("0"),
    filter_id: uuid.UUID | None = None,
    baseline_app: int = 1,
    comparison_app: int = 2,
) -> StreamingResponse:
    await get_accessible_recon(db, current_user, recon_id)
    result = await _run(
        db,
        recon_id,
        variance_threshold=variance_threshold,
        filter_id=filter_id,
        baseline_app=baseline_app,
        comparison_app=comparison_app,
    )
    buffer = io.StringIO()
    dim_names = list(result.rows[0].match_key.keys()) if result.rows else []
    writer = csv.writer(buffer)
    writer.writerow([*dim_names, "baseline_amount", "comparison_amount", "variance", "is_variance"])
    for row in result.rows:
        writer.writerow(
            [
                *(row.match_key[d] for d in dim_names),
                row.baseline_amount if row.baseline_amount is not None else row.app1_amount,
                row.comparison_amount if row.comparison_amount is not None else row.app2_amount,
                row.variance,
                row.is_variance,
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="report_{recon_id}.csv"'},
    )


@router.get("/drill-down", response_model=list[ReportRowRead])
async def drill_down(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    dimension_names: Annotated[list[str], Query()],
    values: Annotated[list[str], Query()],
    variance_threshold: Decimal = Decimal("0"),
    baseline_app: int = 1,
    comparison_app: int = 2,
) -> list[ReportRowRead]:
    await get_accessible_recon(db, current_user, recon_id)
    if len(dimension_names) != len(values):
        raise NotFoundError("dimension_names and values must be the same length")
    wanted = dict(zip(dimension_names, values, strict=True))
    result = await _run(
        db,
        recon_id,
        variance_threshold=variance_threshold,
        filter_id=None,
        baseline_app=baseline_app,
        comparison_app=comparison_app,
    )
    return [row for row in result.rows if all(row.match_key.get(k) == v for k, v in wanted.items())]


@router.get("/last-refresh", response_model=list[LastRefreshRead])
async def last_refresh(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> list[LastRefreshRead]:
    await get_accessible_recon(db, current_user, recon_id)
    results = []
    for app_number in (1, 2):
        stmt = (
            select(ImportRun.completed_at)
            .where(ImportRun.recon_id == recon_id, ImportRun.app_number == app_number)
            .order_by(ImportRun.completed_at.desc().nulls_last())
            .limit(1)
        )
        last = (await db.execute(stmt)).scalar_one_or_none()
        results.append(LastRefreshRead(app_number=app_number, last_refresh=last))
    return results


@router.post("/signoff", response_model=list[SignoffRead])
async def signoff(
    recon_id: uuid.UUID, body: SignoffRequest, current_user: CurrentUser, db: DbSession
) -> list[SignoffRead]:
    await get_accessible_recon(db, current_user, recon_id)
    now = datetime.now(UTC) if body.signed_off else None
    results: list[SignoffRead] = []
    for app_number in body.app_numbers:
        insert_stmt = pg_insert(ReportSignoff).values(
            recon_id=recon_id,
            app_number=app_number,
            signed_off=body.signed_off,
            signed_off_by_id=current_user.id if body.signed_off else None,
            signed_off_at=now,
        )
        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=[ReportSignoff.recon_id, ReportSignoff.app_number],
            set_={
                "signed_off": insert_stmt.excluded.signed_off,
                "signed_off_by_id": insert_stmt.excluded.signed_off_by_id,
                "signed_off_at": insert_stmt.excluded.signed_off_at,
            },
        ).returning(ReportSignoff)
        row = (await db.execute(upsert_stmt)).scalar_one()
        results.append(
            SignoffRead(
                app_number=row.app_number,
                signed_off=row.signed_off,
                signed_off_by_id=row.signed_off_by_id,
                signed_off_at=row.signed_off_at,
            )
        )
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="report.signoff" if body.signed_off else "report.signoff_revoked",
            recon_id=recon_id,
            entity_type="report_signoff",
            entity_id=str(app_number),
            detail={"app_number": str(app_number), "signed_off": str(body.signed_off)},
        )
    await db.commit()
    return results


@router.get("/signoff", response_model=list[SignoffRead])
async def list_signoffs(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> list[SignoffRead]:
    await get_accessible_recon(db, current_user, recon_id)
    stmt = (
        select(ReportSignoff)
        .where(ReportSignoff.recon_id == recon_id)
        .order_by(ReportSignoff.app_number)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        SignoffRead(
            app_number=r.app_number,
            signed_off=r.signed_off,
            signed_off_by_id=r.signed_off_by_id,
            signed_off_at=r.signed_off_at,
        )
        for r in rows
    ]
