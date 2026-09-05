"""Run Report — the reconciliation computation, sign-off, freshness, and
CSV export.

**New-backend-defined contract, not a port — documented as a decision,
same category as Phase 5's JSONB storage choice and Phase 6's bridge-
CSV format.** The old backend's `run_rprt.py` (`Data_Recon_Backend/
.../run_report/functions/run_rprt.py`) delegates the actual row/
variance computation to a stored procedure (`req_type: "create_report"`
/ `"fetch_data"` through `sp_master`) that is not readable Python
anywhere in that repository — the same situation Phase 5 (import
parsing) and Phase 6 (bridge CSV columns) found and resolved the same
way: build a clean, explicit equivalent from what *is* readable, and
say so.

What's readable and ported faithfully:

- **AMOUNT is the measure being compared**, matching every prior
  phase's exclusion list.
- **Matching happens on bridge-resolved values, not raw ones** — Phase
  6's own docstring says bridge mappings normalize a value "*before*
  any cross-system matching happens"; this is the first phase that
  actually performs that matching, so it's the first to depend on that
  design intent being real.
- **A recon-level sign-off is tracked per app number**, confirmed by
  `rcn_signoff.py` (`ReportSignoff`, `app/models/report.py`).
- **A report supports both an "original" (unfiltered) and a "filtered"
  variance figure**, confirmed by `run_rprt.py`'s explicit merge of
  `all_report_original`/`all_report_filtered` results — ported here as
  an optional `filter_id` query param rather than two separate response
  shapes, since the underlying computation is identical either way.

What's new-backend-defined because the old implementation is opaque:

- **The variance formula**: `variance = app1_amount - app2_amount`
  (signed, not absolute — a caller can tell which side is higher),
  where each app's amount is the sum of that app's matching rows'
  `AMOUNT`, sign-flipped per row if that row's match key was built
  using any `BridgeMapping` with `flip_sign=True`. `SyncMapping.
  flip_sign` is deliberately NOT applied here — sync mappings rewrite a
  display value for one specific source value, they don't participate
  in matching or amount computation, so there's nothing principled to
  hang a sign flip on without inventing semantics beyond what Phase 7
  actually built. It stays an explicit known gap (see KT_PHASE8.md)
  rather than a guessed-at behavior.
- **`variance_threshold` is a request-time parameter, not a stored
  per-recon config file.** The old backend reads a flat
  `Recon_name_variance_threshold.json`, matched by a `{recon_name}_`
  string prefix — global mutable file state, exactly the kind of
  pattern this project has moved away from. Callers pass
  `variance_threshold` on each `report/run` call (default `0`, same
  default the old code falls back to when the file doesn't define one
  for a given recon).
- **Rows with `ImportedRow.kickout=True` are excluded from the report
  entirely.** They represent a dimension value bridge mapping couldn't
  resolve — showing them as reconciled/unreconciled either way would be
  misleading; `bridge-data`'s own `kickout` filter is where those
  belong until they're fixed.
"""

import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import NotFoundError
from app.core.recon_access import get_accessible_recon
from app.models.dimension import Dimension
from app.models.import_run import ImportedRow, ImportRun
from app.models.report import ReportFilter, ReportSignoff
from app.schemas.report import (
    LastRefreshRead,
    ReportRowRead,
    ReportRunResponse,
    ReportSummaryRead,
    SignoffRead,
    SignoffRequest,
)
from app.services.bridge_resolve import mapping_key, mapping_lookup_for_recon

router = APIRouter(prefix="/recons/{recon_id}/report", tags=["run-report"])

_REPORT_DIMENSION_EXCLUDE = {"AMOUNT"}


async def _match_dimension_names(db: DbSession, recon_id: uuid.UUID) -> list[str]:
    stmt = (
        select(Dimension.name)
        .where(Dimension.recon_id == recon_id, Dimension.name.notin_(_REPORT_DIMENSION_EXCLUDE))
        .order_by(Dimension.position)
    )
    return list((await db.execute(stmt)).scalars().all())


def _parse_amount(raw: str | None) -> Decimal:
    if raw is None:
        return Decimal("0")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return Decimal("0")


async def _load_rows_for_matching(
    db: DbSession,
    recon_id: uuid.UUID,
    app_number: int,
    filter_criteria: dict[str, list[str]] | None,
) -> list[ImportedRow]:
    stmt = select(ImportedRow).where(
        ImportedRow.recon_id == recon_id,
        ImportedRow.app_number == app_number,
        ImportedRow.kickout.is_(False),
    )
    if filter_criteria:
        for dim_name, allowed_values in filter_criteria.items():
            stmt = stmt.where(ImportedRow.data[dim_name].astext.in_(allowed_values))
    return list((await db.execute(stmt)).scalars().all())


class _MatchGroup:
    __slots__ = ("data", "amount")

    def __init__(self) -> None:
        self.data: dict[str, str] | None = None
        self.amount = Decimal("0")


async def _compute_report(
    db: DbSession,
    recon_id: uuid.UUID,
    *,
    variance_threshold: Decimal,
    filter_criteria: dict[str, list[str]] | None,
) -> ReportRunResponse:
    dim_names = await _match_dimension_names(db, recon_id)
    bridge_lookup = await mapping_lookup_for_recon(db, recon_id)

    def resolve_key_and_sign(row: ImportedRow) -> tuple[tuple[str, ...], bool]:
        key_parts: list[str] = []
        sign = 1
        for dim_name in dim_names:
            raw_value = row.data.get(dim_name, "")
            mapping = bridge_lookup.get(mapping_key(row.app_number, dim_name, raw_value))
            if mapping is not None:
                key_parts.append(mapping.bridge_member)
                if mapping.flip_sign:
                    sign *= -1
            else:
                key_parts.append(raw_value)
        return tuple(key_parts), sign < 0

    groups: dict[tuple[str, ...], dict[int, _MatchGroup]] = {}
    for app_number in (1, 2):
        rows = await _load_rows_for_matching(db, recon_id, app_number, filter_criteria)
        for row in rows:
            key, flip = resolve_key_and_sign(row)
            group = groups.setdefault(key, {})
            entry = group.setdefault(app_number, _MatchGroup())
            entry.data = row.data
            amount = _parse_amount(row.data.get("AMOUNT"))
            entry.amount += -amount if flip else amount

    report_rows: list[ReportRowRead] = []
    variance_count = 0
    for key, by_app in groups.items():
        app1 = by_app.get(1)
        app2 = by_app.get(2)
        app1_amount = app1.amount if app1 else Decimal("0")
        app2_amount = app2.amount if app2 else Decimal("0")
        variance = app1_amount - app2_amount
        is_variance = abs(variance) > variance_threshold
        if is_variance:
            variance_count += 1
        report_rows.append(
            ReportRowRead(
                match_key=dict(zip(dim_names, key, strict=True)),
                app1_data=app1.data if app1 else None,
                app2_data=app2.data if app2 else None,
                app1_amount=app1_amount,
                app2_amount=app2_amount,
                variance=variance,
                is_variance=is_variance,
            )
        )

    total_rows = len(report_rows)
    variance_percentage = (variance_count / total_rows * 100) if total_rows else 0.0
    summary = ReportSummaryRead(
        baseline_app=1,
        comparison_app=2,
        variance_threshold=variance_threshold,
        total_rows=total_rows,
        variance_count=variance_count,
        variance_percentage=round(variance_percentage, 4),
    )
    return ReportRunResponse(rows=report_rows, summary=summary)


async def _resolve_filter_criteria(
    db: DbSession, recon_id: uuid.UUID, filter_id: uuid.UUID | None
) -> dict[str, list[str]] | None:
    if filter_id is None:
        return None
    stmt = select(ReportFilter).where(
        ReportFilter.recon_id == recon_id, ReportFilter.id == filter_id
    )
    report_filter = (await db.execute(stmt)).scalar_one_or_none()
    if report_filter is None:
        raise NotFoundError("Report filter not found")
    return report_filter.criteria


@router.post("/run", response_model=ReportRunResponse)
async def run_report(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    variance_threshold: Decimal = Decimal("0"),
    filter_id: uuid.UUID | None = None,
) -> ReportRunResponse:
    await get_accessible_recon(db, current_user, recon_id)
    criteria = await _resolve_filter_criteria(db, recon_id, filter_id)
    result = await _compute_report(
        db, recon_id, variance_threshold=variance_threshold, filter_criteria=criteria
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
) -> StreamingResponse:
    await get_accessible_recon(db, current_user, recon_id)
    criteria = await _resolve_filter_criteria(db, recon_id, filter_id)
    result = await _compute_report(
        db, recon_id, variance_threshold=variance_threshold, filter_criteria=criteria
    )

    buffer = io.StringIO()
    dim_names = list(result.rows[0].match_key.keys()) if result.rows else []
    writer = csv.writer(buffer)
    writer.writerow([*dim_names, "app1_amount", "app2_amount", "variance", "is_variance"])
    for row in result.rows:
        writer.writerow(
            [
                *(row.match_key[d] for d in dim_names),
                row.app1_amount,
                row.app2_amount,
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
) -> list[ReportRowRead]:
    """Given a resolved match key (parallel `dimension_names`/`values`
    lists, same convention as sync-mapping's `possible-combinations`),
    return just the report row(s) matching it — the underlying raw
    `app1_data`/`app2_data` a summary figure was built from."""
    await get_accessible_recon(db, current_user, recon_id)
    if len(dimension_names) != len(values):
        raise NotFoundError("dimension_names and values must be the same length")
    wanted = dict(zip(dimension_names, values, strict=True))
    result = await _compute_report(
        db, recon_id, variance_threshold=variance_threshold, filter_criteria=None
    )
    return [row for row in result.rows if all(row.match_key.get(k) == v for k, v in wanted.items())]


@router.get("/last-refresh", response_model=list[LastRefreshRead])
async def last_refresh(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> list[LastRefreshRead]:
    """Replaces the old backend's `updatedflag` dirty-bit cache
    invalidation scheme — not needed here since the report is computed
    fresh on every call rather than materialized into `rpt_*` tables, so
    there's no cache to invalidate. This just reports each app's most
    recent completed import as a freshness indicator for the UI."""
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
