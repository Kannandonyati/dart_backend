"""Read-path Transformation run and Apply-All identity mapping generation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.import_run import ImportedRow
from app.models.sync import SyncMapping
from app.schemas.sync import SyncedRowRead
from app.services.bridge_resolve import (
    ResolvedBridgeRow,
    app_type_label,
    load_app_names,
    load_bridged_dimensions,
    mapping_lookup_for_recon,
    resolve_imported_row,
)
from app.services.sync_resolve import (
    SyncedResolution,
    apply_sync_mappings,
    sync_source_value,
    zip_distinct_lists,
)

_SYNC_DIMENSION_EXCLUDE = frozenset({"AMOUNT"})


def _to_synced_row(
    row: ImportedRow,
    app_names: dict[int, str],
    resolved: ResolvedBridgeRow,
    applied: SyncedResolution,
) -> SyncedRowRead:
    return SyncedRowRead(
        id=row.id,
        app_number=row.app_number,
        app_name=app_names.get(row.app_number),
        app_type=app_type_label(row.app_number),
        row_number=row.row_number,
        data=row.data,
        resolved=resolved.resolved,
        synced=applied.synced,
        amount=applied.amount,
        sign_reversed_amount=applied.sign_reversed_amount,
        flip_sign=applied.flip_sign,
    )


async def count_imported_rows(db: AsyncSession, recon_id: uuid.UUID, app_number: int | None) -> int:
    filters = [ImportedRow.recon_id == recon_id]
    if app_number is not None:
        filters.append(ImportedRow.app_number == app_number)
    return (
        await db.execute(select(func.count()).select_from(ImportedRow).where(*filters))
    ).scalar_one()


async def run_transformation_page(
    db: AsyncSession,
    recon_id: uuid.UUID,
    *,
    offset: int,
    page_size: int,
    app_number: int | None,
) -> tuple[list[SyncedRowRead], int]:
    total = await count_imported_rows(db, recon_id, app_number)
    mappings = list(
        (await db.execute(select(SyncMapping).where(SyncMapping.recon_id == recon_id)))
        .scalars()
        .all()
    )
    stmt = select(ImportedRow).where(ImportedRow.recon_id == recon_id)
    if app_number is not None:
        stmt = stmt.where(ImportedRow.app_number == app_number)
    stmt = (
        stmt.order_by(ImportedRow.app_number, ImportedRow.row_number)
        .offset(offset)
        .limit(page_size)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    dim_names = await load_bridged_dimensions(db, recon_id)
    lookup = await mapping_lookup_for_recon(db, recon_id)
    app_names = await load_app_names(db, recon_id)
    results: list[SyncedRowRead] = []
    for row in rows:
        bridged = resolve_imported_row(
            app_number=row.app_number, data=row.data, dim_names=dim_names, lookup=lookup
        )
        applied = apply_sync_mappings(
            app_number=row.app_number,
            data=row.data,
            resolved=bridged.resolved,
            mappings=mappings,
            amount=bridged.amount,
            sign_reversed_amount=bridged.sign_reversed_amount,
        )
        results.append(_to_synced_row(row, app_names, bridged, applied))
    return results, total


def assert_syncable_dimensions(dimension_names: Sequence[str]) -> None:
    if any(name.strip().upper() in _SYNC_DIMENSION_EXCLUDE for name in dimension_names):
        raise AppError("AMOUNT is a measure, not a sync-mapped dimension.", code="not_syncable")


async def distinct_source_lists(
    db: AsyncSession,
    recon_id: uuid.UUID,
    app_number: int,
    dimension_names: Sequence[str],
) -> list[list[str]]:
    stmt = select(ImportedRow).where(
        ImportedRow.recon_id == recon_id, ImportedRow.app_number == app_number
    )
    rows = list((await db.execute(stmt)).scalars().all())
    dim_names = await load_bridged_dimensions(db, recon_id)
    lookup = await mapping_lookup_for_recon(db, recon_id)
    resolved_rows = [
        (
            row,
            resolve_imported_row(
                app_number=row.app_number, data=row.data, dim_names=dim_names, lookup=lookup
            ),
        )
        for row in rows
    ]
    value_lists: list[list[str]] = []
    for dim_name in dimension_names:
        found = {
            value
            for row, bridged in resolved_rows
            if (value := sync_source_value(dim_name, row.data, bridged.resolved))
        }
        value_lists.append(sorted(found))
    return value_lists


async def apply_all_identity_mappings(
    db: AsyncSession,
    recon_id: uuid.UUID,
    *,
    app_number: int,
    dimension_names: list[str],
    concat_delimiter: str,
) -> tuple[int, int]:
    """Old `generate_sync`: identity source→target rows for every zip combo."""
    assert_syncable_dimensions(dimension_names)
    existing = await _existing_source_keys(db, recon_id, app_number, dimension_names)
    created = 0
    skipped = 0
    for source_sync in zip_distinct_lists(
        await distinct_source_lists(db, recon_id, app_number, dimension_names),
        delimiter=concat_delimiter,
    ):
        if source_sync in existing:
            skipped += 1
            continue
        db.add(
            SyncMapping(
                recon_id=recon_id,
                app_number=app_number,
                dimension_names=dimension_names,
                concat_delimiter=concat_delimiter,
                source_sync=source_sync,
                target_sync=source_sync,
                flip_sign=False,
            )
        )
        existing.add(source_sync)
        created += 1
    return created, skipped


async def _existing_source_keys(
    db: AsyncSession,
    recon_id: uuid.UUID,
    app_number: int,
    dimension_names: list[str],
) -> set[str]:
    rows = (
        (
            await db.execute(
                select(SyncMapping.source_sync).where(
                    SyncMapping.recon_id == recon_id,
                    SyncMapping.app_number == app_number,
                    SyncMapping.dimension_names == dimension_names,
                )
            )
        )
        .scalars()
        .all()
    )
    return set(rows)
