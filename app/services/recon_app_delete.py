"""Remove one recon application and every row keyed by that app_number."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.recon_limits import MIN_RECON_APPS
from app.models.bridge import BridgeMapping
from app.models.dimension import Dimension, DimensionMapping, ReconApp
from app.models.import_run import ImportedRow, ImportRun
from app.models.report import ReportSignoff
from app.models.sync import SyncMapping
from app.services.bridge_resolve import assert_app_not_signed_off


async def delete_recon_app(db: AsyncSession, recon_id: uuid.UUID, app_number: int) -> None:
    remaining = (
        await db.execute(
            select(ReconApp.app_number).where(ReconApp.recon_id == recon_id)
        )
    ).scalars().all()
    if len(remaining) <= MIN_RECON_APPS:
        raise ConflictError("A recon must keep at least two applications.")
    if app_number not in remaining:
        raise NotFoundError("Recon app not found")

    await assert_app_not_signed_off(db, recon_id, app_number)

    dim_ids = select(Dimension.id).where(Dimension.recon_id == recon_id)
    await db.execute(
        delete(DimensionMapping).where(
            DimensionMapping.app_number == app_number,
            DimensionMapping.dimension_id.in_(dim_ids),
        )
    )
    await db.execute(
        delete(BridgeMapping).where(
            BridgeMapping.recon_id == recon_id, BridgeMapping.app_number == app_number
        )
    )
    await db.execute(
        delete(SyncMapping).where(
            SyncMapping.recon_id == recon_id, SyncMapping.app_number == app_number
        )
    )
    await db.execute(
        delete(ReportSignoff).where(
            ReportSignoff.recon_id == recon_id, ReportSignoff.app_number == app_number
        )
    )
    await db.execute(
        delete(ImportedRow).where(
            ImportedRow.recon_id == recon_id, ImportedRow.app_number == app_number
        )
    )
    await db.execute(
        delete(ImportRun).where(ImportRun.recon_id == recon_id, ImportRun.app_number == app_number)
    )
    await db.execute(
        delete(ReconApp).where(ReconApp.recon_id == recon_id, ReconApp.app_number == app_number)
    )
