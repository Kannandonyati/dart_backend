"""Dimension CRUD, reordering, mandatory-dimension seeding, and CSV
export/import. Access follows the recon they belong to — see
app/core/recon_access.py.

**Real fix over the old backend, not a port of it**: the old backend's
bulk CSV-import delete path excluded YEAR/PERIOD/AMOUNT
(`dim_bulk_delete`), but its single-dimension delete endpoint had no
such check at all — a direct API call could delete a mandatory
dimension even though the reference frontend's UI never offered the
button for it. Every delete path here (`delete_dimension` and the bulk
replace inside `import_dimensions`) enforces the same protection.

Route order matters: `/seed-mandatory`, `/export`, `/import` are
registered before `/{dimension_id}` — same reason Phase 2's `/available`
and Phase 3's `/mine` were registered before their own `/{id}` routes,
otherwise e.g. `GET .../dimensions/export` would be matched by
`/{dimension_id}` first and 422 on "export" not being a valid UUID.
"""

import csv
import io
import uuid
from collections.abc import Sequence

from fastapi import APIRouter, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from pydantic import ValidationError

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import AppError, ConflictError, NotFoundError
from app.core.recon_access import get_accessible_recon
from app.core.recon_bootstrap import (
    seed_mandatory_dimensions as seed_mandatory_dimensions_for_recon,
)
from app.core.recon_limits import MAX_RECON_APPS
from app.models.dimension import MANDATORY_DIMENSION_NAMES, Dimension, DimensionMapping, ReconApp
from app.schemas.dimension import (
    DimensionCreate,
    DimensionMappingIn,
    DimensionMappingRead,
    DimensionRead,
    DimensionReorder,
    DimensionUpdate,
)

router = APIRouter(prefix="/recons/{recon_id}/dimensions", tags=["dimension-linking"])


def _to_read(dimension: Dimension) -> DimensionRead:
    return DimensionRead(
        id=dimension.id,
        recon_id=dimension.recon_id,
        name=dimension.name,
        position=dimension.position,
        is_mandatory=dimension.name in MANDATORY_DIMENSION_NAMES,
        mappings=[
            DimensionMappingRead(
                app_number=m.app_number,
                in_file=m.in_file,
                column_location=m.column_location,
                default_value=m.default_value,
                is_active=m.is_active,
            )
            for m in dimension.mappings
        ],
    )


async def _list_ordered(db: DbSession, recon_id: uuid.UUID) -> Sequence[Dimension]:
    stmt = (
        select(Dimension)
        .options(selectinload(Dimension.mappings))
        .where(Dimension.recon_id == recon_id)
        .order_by(Dimension.position)
    )
    return (await db.execute(stmt)).scalars().all()


async def _get_dimension(db: DbSession, recon_id: uuid.UUID, dimension_id: uuid.UUID) -> Dimension:
    stmt = (
        select(Dimension)
        .options(selectinload(Dimension.mappings))
        .where(Dimension.recon_id == recon_id, Dimension.id == dimension_id)
    )
    dimension = (await db.execute(stmt)).scalar_one_or_none()
    if dimension is None:
        raise NotFoundError("Dimension not found")
    return dimension


def _build_mappings(mappings_in: list[DimensionMappingIn]) -> list[DimensionMapping]:
    return [
        DimensionMapping(
            app_number=m.app_number,
            in_file=m.in_file,
            column_location=m.column_location,
            default_value=m.default_value,
            is_active=m.is_active,
        )
        for m in mappings_in
    ]


@router.post("", response_model=DimensionRead, status_code=201)
async def create_dimension(
    recon_id: uuid.UUID, body: DimensionCreate, current_user: CurrentUser, db: DbSession
) -> DimensionRead:
    await get_accessible_recon(db, current_user, recon_id)

    existing = await db.execute(
        select(Dimension.id).where(Dimension.recon_id == recon_id, Dimension.name == body.name)
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError(f'A dimension named "{body.name}" already exists on this recon.')

    count = (await db.execute(select(Dimension.id).where(Dimension.recon_id == recon_id))).all()
    dimension = Dimension(
        recon_id=recon_id,
        name=body.name,
        position=len(count),
        mappings=_build_mappings(body.mappings),
    )
    db.add(dimension)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            f'A dimension named "{body.name}" already exists on this recon.'
        ) from exc

    dimension = await _get_dimension(db, recon_id, dimension.id)
    return _to_read(dimension)


@router.get("", response_model=list[DimensionRead])
async def list_dimensions(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> list[DimensionRead]:
    await get_accessible_recon(db, current_user, recon_id)
    dimensions = await _list_ordered(db, recon_id)
    return [_to_read(d) for d in dimensions]


@router.post("/seed-mandatory", response_model=list[DimensionRead])
async def seed_mandatory_dimensions(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> list[DimensionRead]:
    """Idempotent: creates whichever of YEAR/PERIOD/AMOUNT don't already
    exist on this recon, appended after whatever's already there.

    `create_recon` already seeds all three (see
    app/core/recon_bootstrap.py), so on a recon created through this API
    this is a no-op that simply returns the current list. It stays
    exposed as a repair path for recons predating that seeding, and
    because it's the same helper create uses, the two can't drift."""
    await get_accessible_recon(db, current_user, recon_id)
    await seed_mandatory_dimensions_for_recon(db, recon_id)
    await db.commit()
    dimensions = await _list_ordered(db, recon_id)
    return [_to_read(d) for d in dimensions]


_CSV_FIELDS = [
    "Dimension Name",
    "Dimension In File",
    "Location in File",
    "Default Value",
    "Active Flag",
]

# Old DART never keyed import rows by header name. It skipped the first
# line and read serial_no plus five columns per app (check_upload.py
# valid_import). That is why both of these are valid:
#   serial_no, Dimension Name_1, … (export / in-app template)
#   slno, dimension, dim in file, yes type field, no type top member, is_active
#   (repeated per app; MockDataDimension.csv)
_APP_BLOCK = 5

# Old DART exports Active Flag as TRUE/FALSE and Dimension In File as YES/NO
# (see DimensionCards.jsx template and dim_reorder.py). Accept those plus
# yes/no/y/1 so a FCC/EPICOR/TABLEAU export round-trips.
_TRUTHY_FLAGS = frozenset({"yes", "true", "y", "1"})


def _csv_flag(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY_FLAGS


async def _recon_app_numbers(db: DbSession, recon_id: uuid.UUID) -> list[int]:
    numbers = list(
        (
            await db.execute(
                select(ReconApp.app_number)
                .where(ReconApp.recon_id == recon_id)
                .order_by(ReconApp.app_number)
            )
        )
        .scalars()
        .all()
    )
    return numbers or [1, 2]


def _named_app_numbers(fieldnames: list[str] | None) -> list[int]:
    found: set[int] = set()
    for name in fieldnames or []:
        for prefix in ("Dimension Name_", "Dimension In File_", "Active Flag_"):
            if name.startswith(prefix):
                suffix = name.removeprefix(prefix)
                if suffix.isdigit():
                    number = int(suffix)
                    if 1 <= number <= MAX_RECON_APPS:
                        found.add(number)
                break
    return sorted(found)


def _app_numbers_from_header(fieldnames: list[str] | None) -> list[int]:
    named = _named_app_numbers(fieldnames)
    if named:
        numbers = named
        if 1 not in numbers or 2 not in numbers:
            numbers = sorted(set(numbers) | {1, 2})
        return numbers
    n_apps = max(0, len(fieldnames or []) - 1) // _APP_BLOCK
    if n_apps < 1:
        return [1, 2]
    return list(range(1, min(n_apps, MAX_RECON_APPS) + 1))


def _stub_mapping(app_number: int) -> DimensionMappingIn:
    return DimensionMappingIn(
        app_number=app_number, in_file=False, default_value="", is_active=True
    )


def _mapping_from_block(app_number: int, block: Sequence[str]) -> DimensionMappingIn:
    cells = list(block) + [""] * _APP_BLOCK
    _name, in_file_raw, location, default, active = cells[:_APP_BLOCK]
    active_raw = (active or "").strip()
    return DimensionMappingIn(
        app_number=app_number,
        in_file=_csv_flag(in_file_raw),
        column_location=(location or "").strip() or None,
        default_value=default or "",
        is_active=_csv_flag(active) if active_raw else True,
    )


def _mappings_from_positional_row(
    row: list[str], app_numbers: list[int]
) -> tuple[str, list[DimensionMappingIn]]:
    name = (row[1] if len(row) > 1 else "").strip().upper()
    if not name:
        raise ValueError("missing dimension name")
    by_app: dict[int, DimensionMappingIn] = {}
    app_number = 1
    index = 1
    while index + _APP_BLOCK - 1 < len(row) and app_number <= MAX_RECON_APPS:
        by_app[app_number] = _mapping_from_block(app_number, row[index : index + _APP_BLOCK])
        index += _APP_BLOCK
        app_number += 1
    needed = sorted(set(app_numbers) | set(by_app))
    if 1 not in needed or 2 not in needed:
        needed = sorted(set(needed) | {1, 2})
    return name, [by_app.get(n) or _stub_mapping(n) for n in needed]


@router.get("/export")
async def export_dimensions(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> StreamingResponse:
    await get_accessible_recon(db, current_user, recon_id)
    dimensions = await _list_ordered(db, recon_id)
    app_numbers = await _recon_app_numbers(db, recon_id)

    buffer = io.StringIO()
    header = ["serial_no"] + [f"{field}_{n}" for n in app_numbers for field in _CSV_FIELDS]
    writer = csv.writer(buffer)
    writer.writerow(header)
    for i, dimension in enumerate(dimensions, start=1):
        by_app = {m.app_number: m for m in dimension.mappings}
        row = [str(i)]
        for n in app_numbers:
            m = by_app.get(n)
            row += [
                dimension.name,
                "YES" if (m and m.in_file) else "NO",
                (m.column_location if m else None) or "",
                (m.default_value if m else None) or "",
                "TRUE" if (m and m.is_active) else "FALSE",
            ]
        writer.writerow(row)

    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=dimensions.csv"},
    )


@router.post("/import", response_model=list[DimensionRead])
async def import_dimensions(
    recon_id: uuid.UUID, current_user: CurrentUser, db: DbSession, file: UploadFile
) -> list[DimensionRead]:
    """Destructive for custom dimensions, matching the old backend: every
    non-mandatory dimension is replaced by the file. Mandatory YEAR /
    PERIOD / AMOUNT are kept and their mappings are updated from the file
    (old DART FCC exports include those rows with TRUE/YES flags).

    Rows are parsed positionally (serial + 5 columns per app). Header
    names are not required, so MockDataDimension.csv and the numbered
    export template both import."""
    await get_accessible_recon(db, current_user, recon_id)

    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.reader(io.StringIO(raw))
    header = next(reader, None)
    if header is None:
        raise AppError("The import file is empty.", code="invalid_import_row")

    csv_apps = _app_numbers_from_header(header)
    recon_apps = await _recon_app_numbers(db, recon_id)
    app_numbers = sorted(set(csv_apps) | set(recon_apps))

    new_rows: list[tuple[str, list[DimensionMappingIn]]] = []
    for line_no, row in enumerate(reader, start=2):
        if not row or all(not (cell or "").strip() for cell in row):
            continue
        try:
            name, mappings = _mappings_from_positional_row(row, app_numbers)
        except (ValueError, ValidationError) as exc:
            raise AppError(f"Row {line_no}: {exc}", code="invalid_import_row") from exc
        new_rows.append((name, mappings))

    existing = await _list_ordered(db, recon_id)
    existing_by_name = {dimension.name: dimension for dimension in existing}
    for dimension in existing:
        if dimension.name not in MANDATORY_DIMENSION_NAMES:
            await db.delete(dimension)
    await db.flush()

    next_position = sum(1 for d in existing if d.name in MANDATORY_DIMENSION_NAMES)
    for name, mappings in new_rows:
        if name in MANDATORY_DIMENSION_NAMES:
            dimension = existing_by_name.get(name)
            if dimension is None:
                continue
            dimension.mappings = []
            await db.flush()
            dimension.mappings = _build_mappings(mappings)
            continue
        db.add(
            Dimension(
                recon_id=recon_id,
                name=name,
                position=next_position,
                mappings=_build_mappings(mappings),
            )
        )
        next_position += 1

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError("The import file contains a duplicate dimension name.") from exc

    dimensions = await _list_ordered(db, recon_id)
    return [_to_read(d) for d in dimensions]


@router.get("/{dimension_id}", response_model=DimensionRead)
async def get_dimension(
    recon_id: uuid.UUID, dimension_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> DimensionRead:
    await get_accessible_recon(db, current_user, recon_id)
    dimension = await _get_dimension(db, recon_id, dimension_id)
    return _to_read(dimension)


@router.patch("/{dimension_id}", response_model=DimensionRead)
async def update_dimension(
    recon_id: uuid.UUID,
    dimension_id: uuid.UUID,
    body: DimensionUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> DimensionRead:
    await get_accessible_recon(db, current_user, recon_id)
    dimension = await _get_dimension(db, recon_id, dimension_id)

    if body.name is not None and body.name != dimension.name:
        existing = await db.execute(
            select(Dimension.id).where(
                Dimension.recon_id == recon_id,
                Dimension.name == body.name,
                Dimension.id != dimension_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise ConflictError(f'A dimension named "{body.name}" already exists on this recon.')
        dimension.name = body.name

    if body.mappings is not None:
        # Cleared and flushed before the replacements are attached:
        # swapping the collection in a single assignment lets SQLAlchemy
        # order the new INSERTs ahead of the orphan DELETEs in the same
        # flush, which trips uq_dimension_mapping_app (dimension_id,
        # app_number) even though the end state is perfectly valid.
        dimension.mappings = []
        await db.flush()
        dimension.mappings = _build_mappings(body.mappings)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            f'A dimension named "{dimension.name}" already exists on this recon.'
        ) from exc

    dimension = await _get_dimension(db, recon_id, dimension_id)
    return _to_read(dimension)


@router.delete("/{dimension_id}", status_code=204)
async def delete_dimension(
    recon_id: uuid.UUID, dimension_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> None:
    await get_accessible_recon(db, current_user, recon_id)
    dimension = await _get_dimension(db, recon_id, dimension_id)
    if dimension.name in MANDATORY_DIMENSION_NAMES:
        raise AppError(
            f'"{dimension.name}" is a mandatory dimension and cannot be deleted.',
            code="mandatory_dimension",
        )
    await db.delete(dimension)
    await db.commit()


@router.post("/{dimension_id}/reorder", response_model=list[DimensionRead])
async def reorder_dimension(
    recon_id: uuid.UUID,
    dimension_id: uuid.UUID,
    body: DimensionReorder,
    current_user: CurrentUser,
    db: DbSession,
) -> list[DimensionRead]:
    """Full resequencing, not a swap — matches the old backend's
    range-shift reorder exactly in end state (every dimension strictly
    between the old and new position shifts by one), computed here via
    a remove-and-reinsert on the in-memory ordered list rather than a
    hand-rolled range-shift loop; same result, simpler to get right.

    Two-phase position update (temporary negative values, then final
    values) to avoid tripping the `uq_dimension_recon_position` unique
    constraint on an interim state — a naive single-pass update would
    momentarily assign a position another row already holds."""
    await get_accessible_recon(db, current_user, recon_id)
    dimensions = list(await _list_ordered(db, recon_id))
    by_id = {d.id: d for d in dimensions}
    if dimension_id not in by_id:
        raise NotFoundError("Dimension not found")

    ordered_ids = [d.id for d in dimensions]
    ordered_ids.remove(dimension_id)
    new_position = max(0, min(body.new_position, len(ordered_ids)))
    ordered_ids.insert(new_position, dimension_id)

    for temp_offset, dim_id in enumerate(ordered_ids):
        by_id[dim_id].position = -(temp_offset + 1)
    await db.flush()
    for final_position, dim_id in enumerate(ordered_ids):
        by_id[dim_id].position = final_position
    await db.commit()

    reordered = await _list_ordered(db, recon_id)
    return [_to_read(d) for d in reordered]
