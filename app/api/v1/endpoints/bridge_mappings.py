"""Bridge Mapping CRUD, default (identity) seeding, and CSV import.

Mirrors old DART `f_create_default_bridge` / `save_import_data` /
`modify_recon_bridge`:

- Default **replaces** that app's mappings, then identity-inserts
  distinct imported values for every non-AMOUNT dimension.
- File import: `dimension, source member, flip sign, bridge member,
  comments` (comments land in `dim_comment`, matching `save_import.py`).
  Overwrite wipes the app first; merge inserts only (does not update
  existing keys — old import used empty `source_member_old` so MERGE
  never matched).
- Flip sign is true only for yes/true/1/y.
- Signed-off apps cannot be mutated (`f_check_sign_off`).
"""

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.audit import record_audit_log
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.recon_access import get_accessible_recon
from app.models.bridge import KICKOUT_SENTINEL, BridgeMapping
from app.models.import_run import ImportedRow
from app.schemas.bridge import BridgeMappingCreate, BridgeMappingRead, BridgeMappingUpdate
from app.services.bridge_resolve import (
    assert_app_not_signed_off,
    canonical_dimension_name,
    data_value,
    is_amount_dimension,
    load_app_names,
    load_bridged_dimensions,
    load_dimension_aliases,
    mapping_key,
    truthy_flag,
)

router = APIRouter(prefix="/recons/{recon_id}/bridge-mappings", tags=["bridge-members"])


def _to_read(mapping: BridgeMapping, app_name: str | None = None) -> BridgeMappingRead:
    return BridgeMappingRead(
        id=mapping.id,
        recon_id=mapping.recon_id,
        app_number=mapping.app_number,
        app_name=app_name,
        app_type=f"App{mapping.app_number}",
        dimension_name=mapping.dimension_name,
        source_member=mapping.source_member,
        bridge_member=mapping.bridge_member,
        is_kickout=mapping.bridge_member.strip().lower() == KICKOUT_SENTINEL,
        flip_sign=mapping.flip_sign,
        dim_comment=mapping.dim_comment,
        bridge_comment=mapping.bridge_comment,
        je_comment=mapping.je_comment,
        is_invalid=mapping.is_invalid,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


async def _get_mapping(db: DbSession, recon_id: uuid.UUID, mapping_id: uuid.UUID) -> BridgeMapping:
    stmt = select(BridgeMapping).where(
        BridgeMapping.recon_id == recon_id, BridgeMapping.id == mapping_id
    )
    mapping = (await db.execute(stmt)).scalar_one_or_none()
    if mapping is None:
        raise NotFoundError("Bridge mapping not found")
    return mapping


def _set_total_count(response: Response, total: int) -> None:
    response.headers["X-Total-Count"] = str(total)


_CSV_ALIASES = {
    "dimension": "dimension_name",
    "source member": "source_member",
    "bridge member": "bridge_member",
    "flip sign": "flip_sign",
    "comments": "dim_comment",
    "comment": "dim_comment",
    "dimension comment": "dim_comment",
    "bridge comment": "bridge_comment",
    "journal entry comment": "je_comment",
    "je comment": "je_comment",
    "invalid flag": "is_invalid",
    "invalid": "is_invalid",
}


def _normalize_csv_headers(fieldnames: list[str] | None) -> list[str]:
    if not fieldnames:
        return []
    return [
        _CSV_ALIASES.get(name.strip().lower(), name.strip().lower().replace(" ", "_"))
        for name in fieldnames
    ]


async def _find_existing(
    db: DbSession,
    recon_id: uuid.UUID,
    app_number: int,
    dimension_name: str,
    source_member: str,
) -> BridgeMapping | None:
    mappings = (
        (
            await db.execute(
                select(BridgeMapping).where(
                    BridgeMapping.recon_id == recon_id,
                    BridgeMapping.app_number == app_number,
                )
            )
        )
        .scalars()
        .all()
    )
    target = mapping_key(app_number, dimension_name, source_member)
    for mapping in mappings:
        if mapping_key(mapping.app_number, mapping.dimension_name, mapping.source_member) == target:
            return mapping
    return None


@router.post("", response_model=BridgeMappingRead, status_code=201)
async def create_bridge_mapping(
    recon_id: uuid.UUID, body: BridgeMappingCreate, current_user: CurrentUser, db: DbSession
) -> BridgeMappingRead:
    await get_accessible_recon(db, current_user, recon_id)
    await assert_app_not_signed_off(db, recon_id, body.app_number)
    aliases = await load_dimension_aliases(db, recon_id)
    dimension_name = canonical_dimension_name(
        body.dimension_name, body.app_number, aliases
    )
    if is_amount_dimension(dimension_name):
        raise AppError("AMOUNT is a measure, not a bridge-mapped dimension.", code="not_bridgeable")

    if await _find_existing(
        db, recon_id, body.app_number, dimension_name, body.source_member
    ) or (
        dimension_name != body.dimension_name
        and await _find_existing(
            db, recon_id, body.app_number, body.dimension_name, body.source_member
        )
    ):
        raise ConflictError("A mapping for this app/dimension/source value already exists.")

    payload = body.model_dump()
    payload["dimension_name"] = dimension_name
    mapping = BridgeMapping(recon_id=recon_id, **payload)
    db.add(mapping)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "A mapping for this app/dimension/source value already exists."
        ) from exc

    await db.refresh(mapping)
    app_names = await load_app_names(db, recon_id)
    return _to_read(mapping, app_names.get(mapping.app_number))


@router.get("", response_model=list[BridgeMappingRead])
async def list_bridge_mappings(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
    app_number: int | None = None,
) -> list[BridgeMappingRead]:
    await get_accessible_recon(db, current_user, recon_id)
    filters = [BridgeMapping.recon_id == recon_id]
    if app_number is not None:
        filters.append(BridgeMapping.app_number == app_number)
    total = (
        await db.execute(select(func.count()).select_from(BridgeMapping).where(*filters))
    ).scalar_one()
    _set_total_count(response, total)
    stmt = (
        select(BridgeMapping)
        .where(*filters)
        .order_by(
            BridgeMapping.app_number,
            BridgeMapping.dimension_name,
            BridgeMapping.source_member,
        )
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    result = await db.execute(stmt)
    app_names = await load_app_names(db, recon_id)
    return [_to_read(m, app_names.get(m.app_number)) for m in result.scalars().all()]


@router.get("/export")
async def export_bridge_mappings(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    app_number: int | None = None,
) -> StreamingResponse:
    await get_accessible_recon(db, current_user, recon_id)
    filters = [BridgeMapping.recon_id == recon_id]
    if app_number is not None:
        filters.append(BridgeMapping.app_number == app_number)
    mappings = (
        (
            await db.execute(
                select(BridgeMapping)
                .where(*filters)
                .order_by(
                    BridgeMapping.app_number,
                    BridgeMapping.dimension_name,
                    BridgeMapping.source_member,
                )
            )
        )
        .scalars()
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    if app_number is None:
        writer.writerow(
            [
                "App Number",
                "Dimension",
                "Source Member",
                "Flip Sign",
                "Bridge Member",
                "Comment",
                "Dimension Comment",
                "Journal Entry Comment",
                "Invalid Flag",
            ]
        )
        for mapping in mappings:
            writer.writerow(
                [
                    mapping.app_number,
                    mapping.dimension_name,
                    mapping.source_member,
                    "YES" if mapping.flip_sign else "NO",
                    mapping.bridge_member,
                    mapping.bridge_comment or mapping.dim_comment or "",
                    mapping.dim_comment or "",
                    mapping.je_comment or "",
                    "YES" if mapping.is_invalid else "NO",
                ]
            )
        filename = "Bridge_Members_Export.csv"
    else:
        writer.writerow(["Dimension", "Source Member", "Flip Sign", "Bridge Member", "Comment"])
        for mapping in mappings:
            writer.writerow(
                [
                    mapping.dimension_name,
                    mapping.source_member,
                    "YES" if mapping.flip_sign else "NO",
                    mapping.bridge_member,
                    mapping.bridge_comment or mapping.dim_comment or "",
                ]
            )
        filename = f"App{app_number}_Bridge_Export.csv"
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.patch("/{mapping_id}", response_model=BridgeMappingRead)
async def update_bridge_mapping(
    recon_id: uuid.UUID,
    mapping_id: uuid.UUID,
    body: BridgeMappingUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> BridgeMappingRead:
    await get_accessible_recon(db, current_user, recon_id)
    mapping = await _get_mapping(db, recon_id, mapping_id)
    await assert_app_not_signed_off(db, recon_id, mapping.app_number)
    updates = body.model_dump(exclude_unset=True)
    if "source_member" in updates:
        existing = await _find_existing(
            db,
            recon_id,
            mapping.app_number,
            mapping.dimension_name,
            updates["source_member"],
        )
        if existing is not None and existing.id != mapping.id:
            raise ConflictError("A mapping for this app/dimension/source value already exists.")
    for field, value in updates.items():
        setattr(mapping, field, value)
    await db.commit()
    await db.refresh(mapping)
    app_names = await load_app_names(db, recon_id)
    return _to_read(mapping, app_names.get(mapping.app_number))


@router.delete("/{mapping_id}", status_code=204)
async def delete_bridge_mapping(
    recon_id: uuid.UUID, mapping_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await get_accessible_recon(db, current_user, recon_id)
    mapping = await _get_mapping(db, recon_id, mapping_id)
    await assert_app_not_signed_off(db, recon_id, mapping.app_number)
    await db.delete(mapping)
    await db.commit()


@router.post("/default", response_model=list[BridgeMappingRead])
async def default_bridge_mappings(
    recon_id: uuid.UUID, app_number: int, current_user: CurrentUser, db: DbSession
) -> list[BridgeMappingRead]:
    """Old `f_create_default_bridge`: wipe this app's mappings, then
    identity-map every distinct imported value on non-AMOUNT dimensions."""
    await get_accessible_recon(db, current_user, recon_id)
    await assert_app_not_signed_off(db, recon_id, app_number)

    dim_names = await load_bridged_dimensions(db, recon_id)
    await db.execute(
        delete(BridgeMapping).where(
            BridgeMapping.recon_id == recon_id,
            BridgeMapping.app_number == app_number,
        )
    )

    rows = (
        (
            await db.execute(
                select(ImportedRow.data).where(
                    ImportedRow.recon_id == recon_id, ImportedRow.app_number == app_number
                )
            )
        )
        .scalars()
        .all()
    )

    created: list[BridgeMapping] = []
    seen: set[tuple[int, str, str]] = set()
    for data in rows:
        for dim_name in dim_names:
            value = data_value(data, dim_name)
            if not value:
                continue
            key = mapping_key(app_number, dim_name, value)
            if key in seen:
                continue
            seen.add(key)
            created.append(
                BridgeMapping(
                    recon_id=recon_id,
                    app_number=app_number,
                    dimension_name=dim_name,
                    source_member=value,
                    bridge_member=value,
                    flip_sign=False,
                )
            )

    db.add_all(created)
    await db.commit()
    for mapping in created:
        await db.refresh(mapping)
    app_names = await load_app_names(db, recon_id)
    return [_to_read(m, app_names.get(m.app_number)) for m in created]


@router.post("/import", response_model=list[BridgeMappingRead])
async def import_bridge_mappings(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    file: UploadFile,
    app_number: Annotated[int | None, Form()] = None,
    overwrite: Annotated[bool, Form()] = False,
) -> list[BridgeMappingRead]:
    """Overwrite: wipe that app then insert. Merge: insert only — do not
    update existing (app, dimension, source) keys."""
    await get_accessible_recon(db, current_user, recon_id)
    if overwrite and app_number is None:
        raise AppError("Overwrite requires app_number.", code="invalid_import_format")
    if app_number is not None:
        await assert_app_not_signed_off(db, recon_id, app_number)

    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    original_fields = list(reader.fieldnames or [])
    normalized_fields = _normalize_csv_headers(original_fields)
    header_map = dict(zip(original_fields, normalized_fields, strict=True))

    required = {"dimension_name", "source_member", "bridge_member"}
    if app_number is None:
        required.add("app_number")
    if not required.issubset(set(normalized_fields)):
        raise AppError(
            f"CSV must include columns: {', '.join(sorted(required))}",
            code="invalid_import_format",
        )

    if overwrite and app_number is not None:
        await db.execute(
            delete(BridgeMapping).where(
                BridgeMapping.recon_id == recon_id,
                BridgeMapping.app_number == app_number,
            )
        )

    def cell(row: dict[str, str | None], key: str) -> str:
        for original, normalized in header_map.items():
            if normalized == key:
                return (row.get(original) or "").strip()
        return ""

    aliases = await load_dimension_aliases(db, recon_id)
    existing_rows = (
        (await db.execute(select(BridgeMapping).where(BridgeMapping.recon_id == recon_id)))
        .scalars()
        .all()
    )
    existing_keys: dict[tuple[int, str, str], BridgeMapping] = {}
    for mapping in existing_rows:
        existing_keys[
            mapping_key(mapping.app_number, mapping.dimension_name, mapping.source_member)
        ] = mapping
        common = canonical_dimension_name(
            mapping.dimension_name, mapping.app_number, aliases
        )
        existing_keys[mapping_key(mapping.app_number, common, mapping.source_member)] = mapping

    touched: list[BridgeMapping] = []
    seen_in_file: set[tuple[int, str, str]] = set()
    for line_no, row in enumerate(reader, start=2):
        try:
            row_app = app_number if app_number is not None else int(cell(row, "app_number"))
            dimension_name = canonical_dimension_name(
                cell(row, "dimension_name"), row_app, aliases
            )
            source_member = cell(row, "source_member")
            bridge_member = cell(row, "bridge_member")
            if not dimension_name or not source_member or not bridge_member:
                raise ValueError("dimension_name, source_member, and bridge_member are required")
        except (KeyError, ValueError) as exc:
            raise AppError(f"Row {line_no}: {exc}", code="invalid_import_row") from exc

        if is_amount_dimension(dimension_name):
            continue
        if app_number is None:
            await assert_app_not_signed_off(db, recon_id, row_app)

        key = mapping_key(row_app, dimension_name, source_member)
        if key in seen_in_file:
            continue
        seen_in_file.add(key)

        dim_comment = cell(row, "dim_comment") or None
        bridge_comment = cell(row, "bridge_comment") or None
        if dim_comment and not bridge_comment:
            bridge_comment = dim_comment
        je_comment = cell(row, "je_comment") or None
        flip_sign = truthy_flag(cell(row, "flip_sign"))
        is_invalid = truthy_flag(cell(row, "is_invalid"))

        existing = existing_keys.get(key)
        if existing is not None:
            if overwrite:
                existing.dimension_name = dimension_name
                existing.bridge_member = bridge_member
                existing.flip_sign = flip_sign
                existing.dim_comment = dim_comment
                existing.bridge_comment = bridge_comment
                existing.je_comment = je_comment
                existing.is_invalid = is_invalid
                touched.append(existing)
            continue

        new_mapping = BridgeMapping(
            recon_id=recon_id,
            app_number=row_app,
            dimension_name=dimension_name,
            source_member=source_member,
            bridge_member=bridge_member,
            flip_sign=flip_sign,
            dim_comment=dim_comment,
            bridge_comment=bridge_comment,
            je_comment=je_comment,
            is_invalid=is_invalid,
        )
        db.add(new_mapping)
        existing_keys[key] = new_mapping
        touched.append(new_mapping)

    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="bridge_mapping.imported",
        recon_id=recon_id,
        entity_type="bridge_mapping",
        detail={"row_count": str(len(touched)), "overwrite": str(overwrite)},
    )
    await db.commit()
    for mapping in touched:
        await db.refresh(mapping)
    app_names = await load_app_names(db, recon_id)
    return [_to_read(m, app_names.get(m.app_number)) for m in touched]
