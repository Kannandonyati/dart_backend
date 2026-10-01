"""Sync Mapping CRUD, possible combinations, and Apply All Members.

Route order: `/possible-combinations` and `/apply-all` are registered
before `/{mapping_id}` so those literals are not captured as UUIDs.
"""

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.recon_access import get_accessible_recon
from app.models.sync import SyncMapping
from app.schemas.sync import (
    SyncApplyAllRead,
    SyncApplyAllRequest,
    SyncMappingCreate,
    SyncMappingRead,
    SyncMappingUpdate,
)
from app.services.sync_run import (
    apply_all_identity_mappings,
    assert_syncable_dimensions,
    distinct_source_lists,
)

router = APIRouter(prefix="/recons/{recon_id}/sync-mappings", tags=["transformation"])


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
    assert_syncable_dimensions(body.dimension_names)
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
    return [_to_read(m) for m in (await db.execute(stmt)).scalars().all()]


_CSV_FIELDS = (
    "app_number",
    "dimension_names",
    "concat_delimiter",
    "source_sync",
    "target_sync",
    "flip_sign",
)


@router.get("/export")
async def export_sync_mappings(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession, app_number: int | None = None
) -> StreamingResponse:
    await get_accessible_recon(db, current_user, recon_id)
    stmt = select(SyncMapping).where(SyncMapping.recon_id == recon_id)
    if app_number is not None:
        stmt = stmt.where(SyncMapping.app_number == app_number)
    stmt = stmt.order_by(SyncMapping.app_number, SyncMapping.source_sync)
    rows = (await db.execute(stmt)).scalars()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_FIELDS)
    for mapping in rows:
        writer.writerow(
            [
                mapping.app_number,
                "|".join(mapping.dimension_names),
                mapping.concat_delimiter,
                mapping.source_sync,
                mapping.target_sync,
                "TRUE" if mapping.flip_sign else "FALSE",
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sync_mappings.csv"'},
    )


@router.post("/import", response_model=list[SyncMappingRead])
async def import_sync_mappings(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession, file: UploadFile
) -> list[SyncMappingRead]:
    await get_accessible_recon(db, current_user, recon_id)
    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "source_sync" not in {name.strip() for name in reader.fieldnames}:
        raise AppError("The import file is missing required columns.", code="invalid_import_row")
    created: list[SyncMapping] = []
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not (cell or "").strip() for cell in row.values()):
            continue
        try:
            names = [
                part.strip()
                for part in row["dimension_names"].split("|")
                if part.strip()
            ]
            mapping = SyncMapping(
                recon_id=recon_id,
                app_number=int(row["app_number"]),
                dimension_names=names,
                concat_delimiter=(row.get("concat_delimiter") or "-").strip() or "-",
                source_sync=row["source_sync"].strip(),
                target_sync=row["target_sync"].strip(),
                flip_sign=row.get("flip_sign", "FALSE").strip().upper() in {"TRUE", "1", "YES"},
            )
        except (KeyError, ValueError) as exc:
            raise AppError(f"Row {line_no}: {exc}", code="invalid_import_row") from exc
        db.add(mapping)
        created.append(mapping)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("The import file contains a mapping that already exists.") from exc
    return [_to_read(mapping) for mapping in created]


@router.get("/possible-combinations", response_model=list[list[str]])
async def possible_combinations(
    recon_id: uuid.UUID,
    app_number: int,
    dimension_names: Annotated[list[str], Query()],
    current_user: CurrentUser,
    db: DbSession,
) -> list[list[str]]:
    """Old `generate_comb.py`: positional zip of distinct values, not product."""
    await get_accessible_recon(db, current_user, recon_id)
    value_lists = await distinct_source_lists(db, recon_id, app_number, dimension_names)
    return [list(combo) for combo in zip(*value_lists, strict=False)]


@router.post("/apply-all", response_model=SyncApplyAllRead)
async def apply_all_members(
    recon_id: uuid.UUID,
    body: SyncApplyAllRequest,
    current_user: CurrentUser,
    db: DbSession,
) -> SyncApplyAllRead:
    """Old `generate_sync`: identity mappings for every zip combination."""
    await get_accessible_recon(db, current_user, recon_id)
    created, skipped = await apply_all_identity_mappings(
        db,
        recon_id,
        app_number=body.app_number,
        dimension_names=body.dimension_names,
        concat_delimiter=body.concat_delimiter,
    )
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="sync_mapping.apply_all",
        recon_id=recon_id,
        entity_type="sync_mapping",
        detail={"created": str(created), "skipped": str(skipped)},
    )
    await db.commit()
    return SyncApplyAllRead(created=created, skipped=skipped)


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
