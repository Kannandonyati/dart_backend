"""Saved Report Filters — named, reusable criteria a user applies to
`report/run` (via `filter_id`) to see a "filtered" variance figure next
to the unfiltered one. Confirmed against the old backend's `import_filter`
/`update_filter`/`filter_list`/`filter_mem_list` endpoint surface; the
member-list endpoint here follows the same pattern Phase 7's
`possible-combinations` established for populating a dropdown with a
dimension's distinct imported values.

Route order: `/members` is registered before `/{filter_id}` — the same
literal-before-parameterized rule every prior phase has needed.
"""

import uuid

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import ConflictError, NotFoundError
from app.core.recon_access import get_accessible_recon
from app.models.import_run import ImportedRow
from app.models.report import ReportFilter
from app.schemas.report import ReportFilterCreate, ReportFilterRead, ReportFilterUpdate

router = APIRouter(prefix="/recons/{recon_id}/report/filters", tags=["run-report"])


def _to_read(report_filter: ReportFilter) -> ReportFilterRead:
    return ReportFilterRead(
        id=report_filter.id,
        recon_id=report_filter.recon_id,
        name=report_filter.name,
        criteria=report_filter.criteria,
        created_at=report_filter.created_at,
        updated_at=report_filter.updated_at,
    )


async def _get_filter(db: DbSession, recon_id: uuid.UUID, filter_id: uuid.UUID) -> ReportFilter:
    stmt = select(ReportFilter).where(
        ReportFilter.recon_id == recon_id, ReportFilter.id == filter_id
    )
    report_filter = (await db.execute(stmt)).scalar_one_or_none()
    if report_filter is None:
        raise NotFoundError("Report filter not found")
    return report_filter


@router.post("", response_model=ReportFilterRead, status_code=201)
async def create_report_filter(
    recon_id: uuid.UUID, body: ReportFilterCreate, current_user: CurrentUser, db: DbSession
) -> ReportFilterRead:
    await get_accessible_recon(db, current_user, recon_id)
    report_filter = ReportFilter(
        recon_id=recon_id, created_by_id=current_user.id, **body.model_dump()
    )
    db.add(report_filter)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("A filter with this name already exists for this recon.") from exc
    await db.refresh(report_filter)
    return _to_read(report_filter)


@router.get("", response_model=list[ReportFilterRead])
async def list_report_filters(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> list[ReportFilterRead]:
    await get_accessible_recon(db, current_user, recon_id)
    stmt = select(ReportFilter).where(ReportFilter.recon_id == recon_id).order_by(ReportFilter.name)
    result = await db.execute(stmt)
    return [_to_read(f) for f in result.scalars().all()]


@router.get("/members", response_model=list[str])
async def list_filter_members(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    dimension_name: str,
    app_number: int | None = None,
) -> list[str]:
    await get_accessible_recon(db, current_user, recon_id)
    stmt = (
        select(ImportedRow.data[dimension_name].astext)
        .where(ImportedRow.recon_id == recon_id)
        .distinct()
    )
    if app_number is not None:
        stmt = stmt.where(ImportedRow.app_number == app_number)
    values = (await db.execute(stmt)).scalars().all()
    return sorted(v for v in values if v is not None)


@router.patch("/{filter_id}", response_model=ReportFilterRead)
async def update_report_filter(
    recon_id: uuid.UUID,
    filter_id: uuid.UUID,
    body: ReportFilterUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> ReportFilterRead:
    await get_accessible_recon(db, current_user, recon_id)
    report_filter = await _get_filter(db, recon_id, filter_id)
    report_filter.criteria = body.criteria
    await db.commit()
    await db.refresh(report_filter)
    return _to_read(report_filter)


@router.delete("/{filter_id}", status_code=204)
async def delete_report_filter(
    recon_id: uuid.UUID, filter_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await get_accessible_recon(db, current_user, recon_id)
    report_filter = await _get_filter(db, recon_id, filter_id)
    await db.delete(report_filter)
    await db.commit()
