"""Sync Data — the "run transformation" read, computed fresh on every call.

Old dart-db materialized `recon_data.tfn_<id>` from `bridge_<id>`. Here the
same join is computed on read: bridged members × `SyncMapping` overrides.
"""

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.recon_access import get_accessible_recon
from app.schemas.sync import SyncedRowRead
from app.services.sync_run import count_imported_rows, run_transformation_page

router = APIRouter(prefix="/recons/{recon_id}/sync-data", tags=["transformation"])


@router.post("/run", response_model=list[SyncedRowRead])
async def run_transformation(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
    app_number: int | None = None,
) -> list[SyncedRowRead]:
    await get_accessible_recon(db, current_user, recon_id)
    rows, total = await run_transformation_page(
        db,
        recon_id,
        offset=pagination["offset"],
        page_size=pagination["page_size"],
        app_number=app_number,
    )
    response.headers["X-Total-Count"] = str(total)
    return rows


@router.get("/export")
async def export_transformed_data(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    app_number: int | None = None,
) -> StreamingResponse:
    await get_accessible_recon(db, current_user, recon_id)
    total = await count_imported_rows(db, recon_id, app_number)
    rows, _ = await run_transformation_page(
        db, recon_id, offset=0, page_size=max(total, 1), app_number=app_number
    )
    dim_names: list[str] = []
    if rows:
        dim_names = list(rows[0].synced.keys()) or list(rows[0].data.keys())
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["app_number", "app_name", "row_number", *dim_names, "amount", "flip_sign"])
    for row in rows:
        writer.writerow(
            [
                row.app_number,
                row.app_name or "",
                row.row_number,
                *(row.synced.get(name, row.data.get(name, "")) for name in dim_names),
                row.amount,
                row.flip_sign,
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="transformed_{recon_id}.csv"'},
    )
