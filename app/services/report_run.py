"""Run Report matching — old dart-db `f_create_report` FULL OUTER JOIN.

Match keys are bridge-resolved members (fallback raw). Amounts are
`sign_reversed_amount`: bridge `flip_sign` then Transformation
`SyncMapping.flip_sign`, matching `tfn_*` then `sum(sign_reversed_amount)`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models.dimension import Dimension
from app.models.import_run import ImportedRow
from app.models.report import ReportFilter
from app.models.sync import SyncMapping
from app.schemas.report import ReportRowRead, ReportRunResponse, ReportSummaryRead
from app.services.bridge_resolve import (
    format_decimal,
    mapping_key,
    mapping_lookup_for_recon,
    parse_amount,
)
from app.services.sync_resolve import apply_sync_mappings

_REPORT_DIMENSION_EXCLUDE = frozenset({"AMOUNT"})


class _MatchGroup:
    __slots__ = ("data", "amount")

    def __init__(self) -> None:
        self.data: dict[str, str] | None = None
        self.amount = Decimal("0")


async def match_dimension_names(db: AsyncSession, recon_id: uuid.UUID) -> list[str]:
    stmt = (
        select(Dimension.name)
        .where(Dimension.recon_id == recon_id, Dimension.name.notin_(_REPORT_DIMENSION_EXCLUDE))
        .order_by(Dimension.position)
    )
    return list((await db.execute(stmt)).scalars().all())


async def resolve_filter_criteria(
    db: AsyncSession, recon_id: uuid.UUID, filter_id: uuid.UUID | None
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


async def load_rows_for_matching(
    db: AsyncSession,
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


def resolve_key_and_amount(
    row: ImportedRow,
    dim_names: list[str],
    bridge_lookup: dict,
    sync_mappings: list[SyncMapping],
) -> tuple[tuple[str, ...], Decimal]:
    key_parts: list[str] = []
    resolved: dict[str, str] = {}
    sign = Decimal("1")
    for dim_name in dim_names:
        raw_value = row.data.get(dim_name, "")
        mapping = bridge_lookup.get(mapping_key(row.app_number, dim_name, raw_value))
        if mapping is not None:
            key_parts.append(mapping.bridge_member)
            resolved[dim_name] = mapping.bridge_member
            if mapping.flip_sign:
                sign *= Decimal("-1")
        else:
            key_parts.append(raw_value)
            resolved[dim_name] = raw_value
    amount = parse_amount(row.data.get("AMOUNT"))
    bridge_signed = format_decimal(amount * sign)
    applied = apply_sync_mappings(
        app_number=row.app_number,
        data=row.data,
        resolved=resolved,
        mappings=sync_mappings,
        amount=format_decimal(amount),
        sign_reversed_amount=bridge_signed,
    )
    return tuple(key_parts), parse_amount(applied.sign_reversed_amount)


async def compute_report(
    db: AsyncSession,
    recon_id: uuid.UUID,
    *,
    variance_threshold: Decimal,
    filter_criteria: dict[str, list[str]] | None,
    baseline_app: int = 1,
    comparison_app: int = 2,
) -> ReportRunResponse:
    if baseline_app == comparison_app:
        raise AppError("Baseline and comparison apps must differ.", code="same_app")
    dim_names = await match_dimension_names(db, recon_id)
    bridge_lookup = await mapping_lookup_for_recon(db, recon_id)
    sync_mappings = list(
        (await db.execute(select(SyncMapping).where(SyncMapping.recon_id == recon_id)))
        .scalars()
        .all()
    )
    groups: dict[tuple[str, ...], dict[int, _MatchGroup]] = {}
    for app_number in (baseline_app, comparison_app):
        rows = await load_rows_for_matching(db, recon_id, app_number, filter_criteria)
        for row in rows:
            key, signed = resolve_key_and_amount(row, dim_names, bridge_lookup, sync_mappings)
            group = groups.setdefault(key, {})
            entry = group.setdefault(app_number, _MatchGroup())
            entry.data = row.data
            entry.amount += signed
    return _rows_and_summary(groups, dim_names, variance_threshold, baseline_app, comparison_app)


def _rows_and_summary(
    groups: dict[tuple[str, ...], dict[int, _MatchGroup]],
    dim_names: list[str],
    variance_threshold: Decimal,
    baseline_app: int,
    comparison_app: int,
) -> ReportRunResponse:
    report_rows: list[ReportRowRead] = []
    variance_count = 0
    for key, by_app in groups.items():
        app1 = by_app.get(1)
        app2 = by_app.get(2)
        base = by_app.get(baseline_app)
        comp = by_app.get(comparison_app)
        app1_amount = app1.amount if app1 else Decimal("0")
        app2_amount = app2.amount if app2 else Decimal("0")
        base_amount = base.amount if base else Decimal("0")
        comp_amount = comp.amount if comp else Decimal("0")
        variance = base_amount - comp_amount
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
                baseline_amount=base_amount,
                comparison_amount=comp_amount,
            )
        )
    total_rows = len(report_rows)
    pct = (variance_count / total_rows * 100) if total_rows else 0.0
    return ReportRunResponse(
        rows=report_rows,
        summary=ReportSummaryRead(
            baseline_app=baseline_app,
            comparison_app=comparison_app,
            variance_threshold=variance_threshold,
            total_rows=total_rows,
            variance_count=variance_count,
            variance_percentage=round(pct, 4),
        ),
    )
