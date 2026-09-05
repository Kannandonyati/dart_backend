"""Sync Mapping CRUD and "possible combinations" candidate generation.

Route order: `/possible-combinations` is registered before
`/{mapping_id}` — same literal-before-parameterized rule every prior
phase has needed.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.recon_access import get_accessible_recon
from app.models.import_run import ImportedRow
from app.models.sync import SyncMapping
from app.schemas.sync import SyncMappingCreate, SyncMappingRead, SyncMappingUpdate

router = APIRouter(prefix="/recons/{recon_id}/sync-mappings", tags=["transformation"])

_SYNC_DIMENSION_EXCLUDE = {"AMOUNT"}
"""Excluded from sync mapping for the same reason it's excluded from
Bridge mapping (Phase 6): AMOUNT is the measure being reconciled, not a
matching/lookup key."""


def _to_read(mapping: SyncMapping) -> SyncMappingRead:
    return SyncMappingRead(
        id=mapping.id,
        recon_id=mapping.recon_id,
        app_number=mapping.app_number,
        dimension_names=mapping.dimension_names,
        concat_delimiter=mapping.concat_delimiter,
        source_sync=mapping.source_sync,
        target_sync=mapping.target_sync,
        flip_sign=mapping.flip_sign,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


async def _get_mapping(db: DbSession, recon_id: uuid.UUID, mapping_id: uuid.UUID) -> SyncMapping:
    stmt = select(SyncMapping).where(SyncMapping.recon_id == recon_id, SyncMapping.id == mapping_id)
    mapping = (await db.execute(stmt)).scalar_one_or_none()
    if mapping is None:
        raise NotFoundError("Sync mapping not found")
    return mapping


@router.post("", response_model=SyncMappingRead, status_code=201)
async def create_sync_mapping(
    recon_id: uuid.UUID, body: SyncMappingCreate, current_user: CurrentUser, db: DbSession
) -> SyncMappingRead:
    await get_accessible_recon(db, current_user, recon_id)
    if any(d.strip().upper() in _SYNC_DIMENSION_EXCLUDE for d in body.dimension_names):
        raise AppError("AMOUNT is a measure, not a sync-mapped dimension.", code="not_syncable")

    existing = await db.execute(
        select(SyncMapping.id).where(
            SyncMapping.recon_id == recon_id,
            SyncMapping.app_number == body.app_number,
            SyncMapping.dimension_names == body.dimension_names,
            SyncMapping.source_sync == body.source_sync,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(
            "A mapping for this app/dimension-combination/source value already exists."
        )

    mapping = SyncMapping(recon_id=recon_id, **body.model_dump())
    db.add(mapping)
    try:
        await db.flush()
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="sync_mapping.created",
            recon_id=recon_id,
            entity_type="sync_mapping",
            entity_id=str(mapping.id),
            detail={"dimension_names": ", ".join(body.dimension_names)},
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "A mapping for this app/dimension-combination/source value already exists."
        ) from exc

    await db.refresh(mapping)
    return _to_read(mapping)


@router.get("", response_model=list[SyncMappingRead])
async def list_sync_mappings(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    app_number: int | None = None,
) -> list[SyncMappingRead]:
    await get_accessible_recon(db, current_user, recon_id)
    stmt = select(SyncMapping).where(SyncMapping.recon_id == recon_id)
    if app_number is not None:
        stmt = stmt.where(SyncMapping.app_number == app_number)
    stmt = stmt.order_by(SyncMapping.dimension_names, SyncMapping.source_sync)
    result = await db.execute(stmt)
    return [_to_read(m) for m in result.scalars().all()]


@router.get("/possible-combinations", response_model=list[list[str]])
async def possible_combinations(
    recon_id: uuid.UUID,
    app_number: int,
    dimension_names: Annotated[list[str], Query()],
    current_user: CurrentUser,
    db: DbSession,
) -> list[list[str]]:
    """Candidate composite-key values for setting up a concat sync
    mapping. Confirmed against the old backend's `generate_comb.py`:
    row-positional `zip(*lists)` of each dimension's distinct values, not
    every cross-combination (`itertools.product`) — a genuinely
    surprising design choice that only makes sense when the dimensions
    are already row-aligned in the source file, but it's what's there,
    so it's what's replicated. Each dimension's distinct-value list is
    sorted here for determinism; the old backend's own ordering (live
    scan order from its stored procedure) isn't reproducible or
    meaningful outside that context."""
    await get_accessible_recon(db, current_user, recon_id)

    value_lists: list[list[str]] = []
    for dim_name in dimension_names:
        values = (
            (
                await db.execute(
                    select(ImportedRow.data[dim_name].astext)
                    .where(ImportedRow.recon_id == recon_id, ImportedRow.app_number == app_number)
                    .distinct()
                )
            )
            .scalars()
            .all()
        )
        value_lists.append(sorted(v for v in values if v is not None))

    return [list(combo) for combo in zip(*value_lists, strict=False)]


@router.patch("/{mapping_id}", response_model=SyncMappingRead)
async def update_sync_mapping(
    recon_id: uuid.UUID,
    mapping_id: uuid.UUID,
    body: SyncMappingUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> SyncMappingRead:
    await get_accessible_recon(db, current_user, recon_id)
    mapping = await _get_mapping(db, recon_id, mapping_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(mapping, field, value)
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="sync_mapping.updated",
        recon_id=recon_id,
        entity_type="sync_mapping",
        entity_id=str(mapping.id),
    )
    await db.commit()
    await db.refresh(mapping)
    return _to_read(mapping)


@router.delete("/{mapping_id}", status_code=204)
async def delete_sync_mapping(
    recon_id: uuid.UUID, mapping_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await get_accessible_recon(db, current_user, recon_id)
    mapping = await _get_mapping(db, recon_id, mapping_id)
    await db.delete(mapping)
    await db.commit()
