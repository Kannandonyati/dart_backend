"""Sync Data — the "run transformation" read, computed fresh on every
call rather than cached in a per-recon table the way the old backend's
`create_tfn` did (same anti-pattern already avoided in Phases 5/6 — see
those KTs and architecture.md §1/§2).

**No Celery task, unlike Bridge Members' `run_bridge` (Phase 6) — a
deliberate difference, not an oversight.** Bridge's task exists because
it writes a real side effect back to storage (`ImportedRow.kickout`).
Transformation has no equivalent: `generate_sync`/`generate_comb`
notwithstanding, nothing in the old backend's readable code suggests a
per-row flag transformation needs to persist. Resolving a row's synced
values is a pure computed join between `ImportedRow.data` and
`SyncMapping` — same shape as Bridge's `resolved` field in
`bridge-data`, which is also computed on read, not written back. If
real per-row compute cost at scale later proves this needs to move to a
background job, that's a mechanical change (wrap this in a Celery task,
same shape as `bridge_tasks.py`) — not a redesign.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.recon_access import get_accessible_recon
from app.models.import_run import ImportedRow
from app.models.sync import SyncMapping
from app.schemas.sync import SyncedRowRead

router = APIRouter(prefix="/recons/{recon_id}/sync-data", tags=["transformation"])


def _resolve(row: ImportedRow, mappings: list[SyncMapping]) -> dict[str, str]:
    synced: dict[str, str] = {}
    for mapping in mappings:
        if mapping.app_number != row.app_number:
            continue
        raw_values = [row.data.get(d) for d in mapping.dimension_names]
        if any(v is None for v in raw_values):
            continue
        values = [v for v in raw_values if v is not None]
        source_key = mapping.concat_delimiter.join(values)
        if source_key == mapping.source_sync:
            group_key = "-".join(mapping.dimension_names)
            synced[group_key] = mapping.target_sync
    return synced


@router.post("/run", response_model=list[SyncedRowRead])
async def run_transformation(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
    app_number: int | None = None,
) -> list[SyncedRowRead]:
    await get_accessible_recon(db, current_user, recon_id)

    mappings = (
        (await db.execute(select(SyncMapping).where(SyncMapping.recon_id == recon_id)))
        .scalars()
        .all()
    )

    stmt = select(ImportedRow).where(ImportedRow.recon_id == recon_id)
    if app_number is not None:
        stmt = stmt.where(ImportedRow.app_number == app_number)
    stmt = (
        stmt.order_by(ImportedRow.app_number, ImportedRow.row_number)
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    rows = (await db.execute(stmt)).scalars().all()

    return [
        SyncedRowRead(
            id=row.id,
            app_number=row.app_number,
            row_number=row.row_number,
            data=row.data,
            synced=_resolve(row, list(mappings)),
        )
        for row in rows
    ]
