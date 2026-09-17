"""Sync Data — the "run transformation" read, computed fresh on every call.

Old dart-db materialized `recon_data.tfn_<id>` from `bridge_<id>`. Here the
same join is computed on read: bridged members × `SyncMapping` overrides.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.recon_access import get_accessible_recon
from app.schemas.sync import SyncedRowRead
from app.services.sync_run import run_transformation_page

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
