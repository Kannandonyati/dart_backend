"""Kickouts as unmapped source members — old `kickout_list.py`.

Not whole imported rows. A kickout is a distinct (app, dimension,
source_member) that either has no mapping or maps to the `kickout`
sentinel — but only after that app has at least one mapping (template
or Default). Zero mappings means an empty kickouts list, matching old
DART. Resolve writes a real mapping; Default Kickouts identity-maps
each current kickout (merge, does not wipe real mappings).
"""

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.api.v1.endpoints.bridge_mappings import _to_read
from app.core.exceptions import AppError
from app.core.recon_access import get_accessible_recon
from app.models.bridge import BridgeMapping
from app.models.import_run import ImportedRow
from app.schemas.bridge import BridgeKickoutRead, BridgeKickoutResolve, BridgeMappingRead
from app.services.bridge_resolve import (
    KickoutMember,
    assert_app_not_signed_off,
    discover_kickout_members,
    is_amount_dimension,
    load_app_names,
    load_bridged_dimensions,
    load_dimension_aliases,
    load_mappings,
    mapping_key,
    mapping_lookup_for_recon,
)

router = APIRouter(prefix="/recons/{recon_id}/bridge-kickouts", tags=["bridge-members"])


def _to_kickout_read(item: KickoutMember) -> BridgeKickoutRead:
    return BridgeKickoutRead(
        app_number=item.app_number,
        app_name=item.app_name,
        app_type=f"App{item.app_number}",
        dimension_name=item.dimension_name,
        source_member=item.source_member,
        bridge_member=item.bridge_member,
        Common_dimension_name=item.dimension_name,
        Source_member=item.source_member,
        Bridge_member=item.bridge_member,
    )


async def _kickouts_for_recon(
    db: DbSession, recon_id: uuid.UUID, app_number: int | None = None
) -> list[KickoutMember]:
    dim_names = await load_bridged_dimensions(db, recon_id)
    mappings = await load_mappings(db, recon_id)
    aliases = await load_dimension_aliases(db, recon_id)
    lookup = await mapping_lookup_for_recon(db, recon_id)
    app_names = await load_app_names(db, recon_id)
    filters = [ImportedRow.recon_id == recon_id]
    if app_number is not None:
        filters.append(ImportedRow.app_number == app_number)
    rows = list((await db.execute(select(ImportedRow).where(*filters))).scalars().all())
    return discover_kickout_members(
        rows=rows,
        dim_names=dim_names,
        lookup=lookup,
        mappings=mappings,
        app_names=app_names,
        app_number=app_number,
        aliases=aliases,
    )


@router.get("", response_model=list[BridgeKickoutRead])
async def list_bridge_kickouts(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    response: Response,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
    app_number: int | None = None,
) -> list[BridgeKickoutRead]:
    await get_accessible_recon(db, current_user, recon_id)
    items = await _kickouts_for_recon(db, recon_id, app_number)
    response.headers["X-Total-Count"] = str(len(items))
    page = items[pagination["offset"] : pagination["offset"] + pagination["page_size"]]
    return [_to_kickout_read(item) for item in page]


@router.get("/export")
async def export_bridge_kickouts(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    app_number: int | None = None,
) -> StreamingResponse:
    await get_accessible_recon(db, current_user, recon_id)
    items = await _kickouts_for_recon(db, recon_id, app_number)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["app_name", "Common_dimension_name", "Source_member", "Bridge_member"])
    for item in items:
        writer.writerow(
            [
                item.app_name or f"App{item.app_number}",
                item.dimension_name,
                item.source_member,
                item.bridge_member,
            ]
        )
    buffer.seek(0)
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=Bridge_Kick_out_Export.csv"},
    )


@router.post("", response_model=BridgeMappingRead)
async def resolve_bridge_kickout(
    recon_id: uuid.UUID,
    body: BridgeKickoutResolve,
    current_user: CurrentUser,
    db: DbSession,
) -> BridgeMappingRead:
    await get_accessible_recon(db, current_user, recon_id)
    await assert_app_not_signed_off(db, recon_id, body.app_number)
    if is_amount_dimension(body.dimension_name):
        raise AppError("AMOUNT is a measure, not a bridge-mapped dimension.", code="not_bridgeable")

    mappings = (
        (
            await db.execute(
                select(BridgeMapping).where(
                    BridgeMapping.recon_id == recon_id,
                    BridgeMapping.app_number == body.app_number,
                )
            )
        )
        .scalars()
        .all()
    )
    target = mapping_key(body.app_number, body.dimension_name, body.source_member)
    existing = next(
        (
            m
            for m in mappings
            if mapping_key(m.app_number, m.dimension_name, m.source_member) == target
        ),
        None,
    )
    if existing is not None:
        existing.bridge_member = body.bridge_member
        existing.flip_sign = body.flip_sign
        existing.dim_comment = body.dim_comment
        existing.bridge_comment = body.bridge_comment
        existing.je_comment = body.je_comment
        existing.is_invalid = False
        mapping = existing
    else:
        mapping = BridgeMapping(
            recon_id=recon_id,
            app_number=body.app_number,
            dimension_name=body.dimension_name,
            source_member=body.source_member,
            bridge_member=body.bridge_member,
            flip_sign=body.flip_sign,
            dim_comment=body.dim_comment,
            bridge_comment=body.bridge_comment,
            je_comment=body.je_comment,
        )
        db.add(mapping)

    await db.commit()
    await db.refresh(mapping)
    app_names = await load_app_names(db, recon_id)
    return _to_read(mapping, app_names.get(mapping.app_number))


@router.post("/default", response_model=list[BridgeMappingRead])
async def default_bridge_kickouts(
    recon_id: uuid.UUID,
    current_user: CurrentUser,
    db: DbSession,
    app_number: int | None = None,
) -> list[BridgeMappingRead]:
    """Old `def_kickouts`: identity-map every current kickout (merge)."""
    await get_accessible_recon(db, current_user, recon_id)
    items = await _kickouts_for_recon(db, recon_id, app_number)
    apps = {item.app_number for item in items}
    for app in apps:
        await assert_app_not_signed_off(db, recon_id, app)

    lookup = await mapping_lookup_for_recon(db, recon_id)
    touched: list[BridgeMapping] = []
    for item in items:
        key = mapping_key(item.app_number, item.dimension_name, item.source_member)
        existing = lookup.get(key)
        if existing is not None:
            existing.bridge_member = item.source_member
            existing.flip_sign = False
            existing.is_invalid = False
            touched.append(existing)
        else:
            created = BridgeMapping(
                recon_id=recon_id,
                app_number=item.app_number,
                dimension_name=item.dimension_name,
                source_member=item.source_member,
                bridge_member=item.source_member,
                flip_sign=False,
            )
            db.add(created)
            lookup[key] = created
            touched.append(created)

    await db.commit()
    for mapping in touched:
        await db.refresh(mapping)
    app_names = await load_app_names(db, recon_id)
    return [_to_read(m, app_names.get(m.app_number)) for m in touched]
