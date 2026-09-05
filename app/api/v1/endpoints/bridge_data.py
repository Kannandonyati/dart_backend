"""Read-back of bridge-resolved data — old `get_bridge_data`.

Resolved canonical values, kickout sentinel, and `sign_reversed_amount`
(product of per-dimension flip_sign × amount) are computed at read time
from `ImportedRow.data` × `BridgeMapping`, matching
`bridge_loop_query`. `ImportedRow.kickout` is still written by Run
Bridge for report exclusion; this read path recomputes so a mapping
change is visible without re-running.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.recon_access import get_accessible_recon
from app.models.import_run import ImportedRow
from app.schemas.bridge import BridgeDataRowRead
from app.services.bridge_resolve import (
    app_type_label,
    mapping_lookup_for_recon,
    load_app_names,
    load_bridged_dimensions,
    resolve_imported_row,
)

router = APIRouter(prefix="/recons/{recon_id}/bridge-data", tags=["bridge-members"])


async def _resolve(
    db: DbSession, recon_id: uuid.UUID, rows: list[ImportedRow]
) -> list[BridgeDataRowRead]:
    dim_names = await load_bridged_dimensions(db, recon_id)
    lookup = await mapping_lookup_for_recon(db, recon_id)
    app_names = await load_app_names(db, recon_id)

    results = []
    for row in rows:
        resolved = resolve_imported_row(
            app_number=row.app_number,
            data=row.data,
            dim_names=dim_names,
            lookup=lookup,
        )
        results.append(
            BridgeDataRowRead(
                id=row.id,
                app_number=row.app_number,
                app_name=app_names.get(row.app_number),
                app_type=app_type_label(row.app_number),
                row_number=row.row_number,
                data=row.data,
                resolved=resolved.resolved,
                kickout=resolved.kickout,
                amount=resolved.amount,
                sign_reversed_amount=resolved.sign_reversed_amount,
                user_comment=resolved.user_comment,
                je_comment=resolved.je_comment,
            )
        )
    return results


@router.get("", response_model=list[BridgeDataRowRead])
async def list_bridge_data(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
    app_number: int | None = None,
    kickout: Annotated[bool | None, Query()] = None,
) -> list[BridgeDataRowRead]:
    await get_accessible_recon(db, current_user, recon_id)
    filters = [ImportedRow.recon_id == recon_id]
    if app_number is not None:
        filters.append(ImportedRow.app_number == app_number)
    if kickout is not None:
        filters.append(ImportedRow.kickout == kickout)
    total = (
        await db.execute(select(func.count()).select_from(ImportedRow).where(*filters))
    ).scalar_one()
    response.headers["X-Total-Count"] = str(total)
    stmt = (
        select(ImportedRow)
        .where(*filters)
        .order_by(ImportedRow.app_number, ImportedRow.row_number)
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    rows = (await db.execute(stmt)).scalars().all()
    return await _resolve(db, recon_id, list(rows))
