"""Shared Bridge Members resolution — the old DART `bridge_loop_query`.

Old SQL (`recon_data.mstr_qry_tbl` `bridge_loop_query`):
- left-join each non-AMOUNT dimension with `lower(source) = lower(mapping)`
- unmapped values coalesce to the literal sentinel `kickout`
- `sign_reversed_amount` is `product(flip_sign ±1) * amount`
- `not is_invalid` mappings are excluded from the join
- comments concatenate as dim_comments then bridge_comments, joined by `^`

Kickouts (old `kickout_list.py`) are distinct *source members* whose
resolved `bridge_{dim}` is `kickout` **after mappings exist for that
app** (template upload or Default), plus mapping rows stored as the
sentinel. Imported data with zero mappings is not a kickout list —
old DART's Kickouts tab stayed empty until a template existed. They
are not whole imported rows.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import AppError
from app.models.bridge import KICKOUT_SENTINEL, BridgeMapping
from app.models.dimension import Dimension, ReconApp
from app.models.import_run import ImportedRow, ImportRun, ImportStatus
from app.models.report import ReportSignoff
from app.services.file_storage import read_upload_async

BRIDGED_DIMENSION_EXCLUDE = frozenset({"AMOUNT"})


def is_amount_dimension(name: str) -> bool:
    return name.strip().upper() in BRIDGED_DIMENSION_EXCLUDE


def is_kickout_member(value: str | None) -> bool:
    return bool(value) and value.strip().lower() == KICKOUT_SENTINEL


def app_type_label(app_number: int) -> str:
    return f"App{app_number}"


def mapping_key(app_number: int, dimension_name: str, source_member: str) -> tuple[int, str, str]:
    return (app_number, dimension_name.strip().lower(), source_member.strip().lower())


def data_value(data: dict[str, str], dim_name: str) -> str:
    if dim_name in data:
        return str(data.get(dim_name) or "").strip()
    target = dim_name.strip().lower()
    for key, value in data.items():
        if key.strip().lower() == target:
            return str(value or "").strip()
    return ""


def parse_amount(raw: str | None) -> Decimal:
    if raw is None or str(raw).strip() == "":
        return Decimal("0")
    try:
        return Decimal(str(raw).strip().replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def format_decimal(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(quantized, "f")


def truthy_flag(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"yes", "true", "1", "y"}


def canonical_dimension_name(
    raw: str,
    app_number: int,
    aliases: dict[tuple[int, str], str],
) -> str:
    stripped = raw.strip()
    return aliases.get((app_number, stripped.lower()), stripped)


def build_mapping_lookup(
    mappings: Sequence[BridgeMapping],
    aliases: dict[tuple[int, str], str] | None = None,
) -> dict[tuple[int, str, str], BridgeMapping]:
    """Index mappings by common dimension name.

    Old DART stored the source-file column (`COSTCENTRE`, `GEO`) and
    joined through `dim_id` onto the common dimension (`PRACTICE`,
    `GEOGRAPHY`). Imported rows here are keyed by the common name, so
    lookups must accept both.
    """
    aliases = aliases or {}
    lookup: dict[tuple[int, str, str], BridgeMapping] = {}
    for mapping in mappings:
        if mapping.is_invalid:
            continue
        common = canonical_dimension_name(
            mapping.dimension_name, mapping.app_number, aliases
        )
        lookup[mapping_key(mapping.app_number, common, mapping.source_member)] = mapping
        stored = mapping.dimension_name
        if stored.strip().lower() != common.strip().lower():
            lookup[mapping_key(mapping.app_number, stored, mapping.source_member)] = mapping
    return lookup


async def load_dimension_aliases(
    db: AsyncSession, recon_id: uuid.UUID
) -> dict[tuple[int, str], str]:
    """`(app_number, file-or-common name lower)` → common Dimension.name.

    File-column aliases come from the latest completed import's header
    at each dimension's `column_location`, matching old
    `recon_dimension.dimension`.
    """
    aliases: dict[tuple[int, str], str] = {}
    dims = (
        (
            await db.execute(
                select(Dimension)
                .options(selectinload(Dimension.mappings))
                .where(Dimension.recon_id == recon_id)
            )
        )
        .scalars()
        .all()
    )
    apps = {
        app.app_number: app
        for app in (
            await db.execute(select(ReconApp).where(ReconApp.recon_id == recon_id))
        )
        .scalars()
        .all()
    }
    for dim in dims:
        if is_amount_dimension(dim.name):
            continue
        for mapping in dim.mappings:
            aliases[(mapping.app_number, dim.name.strip().lower())] = dim.name

    runs = (
        (
            await db.execute(
                select(ImportRun)
                .where(
                    ImportRun.recon_id == recon_id,
                    ImportRun.status == ImportStatus.COMPLETED,
                )
                .order_by(ImportRun.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    headers_by_app: dict[int, list[str]] = {}
    seen_apps: set[int] = set()
    for run in runs:
        if run.app_number in seen_apps:
            continue
        seen_apps.add(run.app_number)
        app = apps.get(run.app_number)
        if app is None or not app.has_header:
            continue
        try:
            raw = await read_upload_async(run.file_path)
        except OSError:
            continue
        first_line = raw.decode("utf-8-sig").splitlines()[:1]
        if not first_line:
            continue
        headers_by_app[run.app_number] = next(
            csv.reader(io.StringIO(first_line[0]), delimiter=app.delimiter)
        )

    for dim in dims:
        if is_amount_dimension(dim.name):
            continue
        for mapping in dim.mappings:
            if not mapping.in_file or not mapping.column_location:
                continue
            location = mapping.column_location.strip()
            try:
                index = int(location)
            except ValueError:
                aliases[(mapping.app_number, location.lower())] = dim.name
                continue
            headers = headers_by_app.get(mapping.app_number)
            if not headers or index < 1 or index > len(headers):
                continue
            header = headers[index - 1].strip()
            if header:
                aliases[(mapping.app_number, header.lower())] = dim.name
    return aliases


def enrich_lookup_with_imported_values(
    lookup: dict[tuple[int, str, str], BridgeMapping],
    mappings: Sequence[BridgeMapping],
    rows: Sequence[ImportedRow],
    dim_names: Sequence[str],
) -> None:
    """If a mapping was stored under the source-file column name, also
    index it by the common dimension whose imported values match.

    Old DART joined `lower(a."<file_dim>") = lower(source_member)` via
    dim_id. After import, file columns live under the common name, so
    `COSTCENTRE`/`CPM-Quanta` must still resolve `PRACTICE`/`CPM-Quanta`.
    """
    known = {name.strip().lower() for name in dim_names}
    for mapping in mappings:
        if mapping.is_invalid:
            continue
        if mapping.dimension_name.strip().lower() in known:
            continue
        if any(
            mapping_key(mapping.app_number, dim_name, mapping.source_member) in lookup
            for dim_name in dim_names
        ):
            continue
        source = mapping.source_member.strip().lower()
        if not source:
            continue
        matches: set[str] = set()
        for row in rows:
            if row.app_number != mapping.app_number:
                continue
            for dim_name in dim_names:
                if data_value(row.data, dim_name).strip().lower() == source:
                    matches.add(dim_name)
        if len(matches) != 1:
            continue
        lookup[
            mapping_key(mapping.app_number, next(iter(matches)), mapping.source_member)
        ] = mapping


async def mapping_lookup_for_recon(
    db: AsyncSession, recon_id: uuid.UUID
) -> dict[tuple[int, str, str], BridgeMapping]:
    mappings = await load_mappings(db, recon_id)
    aliases = await load_dimension_aliases(db, recon_id)
    lookup = build_mapping_lookup(mappings, aliases)
    dim_names = await load_bridged_dimensions(db, recon_id)
    rows = list(
        (await db.execute(select(ImportedRow).where(ImportedRow.recon_id == recon_id)))
        .scalars()
        .all()
    )
    enrich_lookup_with_imported_values(lookup, mappings, rows, dim_names)
    return lookup


@dataclass(frozen=True)
class ResolvedBridgeRow:
    resolved: dict[str, str]
    kickout: bool
    amount: str
    sign_reversed_amount: str
    user_comment: str
    je_comment: str


def resolve_imported_row(
    *,
    app_number: int,
    data: dict[str, str],
    dim_names: Sequence[str],
    lookup: dict[tuple[int, str, str], BridgeMapping],
) -> ResolvedBridgeRow:
    resolved: dict[str, str] = {}
    kickout = False
    sign = Decimal("1")
    dim_comments: list[str] = []
    bridge_comments: list[str] = []
    je_comments: list[str] = []

    for dim_name in dim_names:
        if is_amount_dimension(dim_name):
            continue
        source = data_value(data, dim_name)
        mapping = (
            lookup.get(mapping_key(app_number, dim_name, source)) if source else None
        )
        if mapping is None or is_kickout_member(mapping.bridge_member):
            resolved[dim_name] = KICKOUT_SENTINEL
            kickout = True
            dim_comments.append("")
            bridge_comments.append("")
            je_comments.append("")
            continue
        resolved[dim_name] = mapping.bridge_member
        if mapping.flip_sign:
            sign *= Decimal("-1")
        dim_comments.append(mapping.dim_comment or "")
        bridge_comments.append(mapping.bridge_comment or "")
        je_comments.append(mapping.je_comment or "")

    amount = parse_amount(data_value(data, "AMOUNT"))
    return ResolvedBridgeRow(
        resolved=resolved,
        kickout=kickout,
        amount=format_decimal(amount),
        sign_reversed_amount=format_decimal(amount * sign),
        user_comment="^".join(dim_comments) + "^".join(bridge_comments),
        je_comment="^".join(je_comments),
    )


@dataclass(frozen=True)
class KickoutMember:
    app_number: int
    app_name: str | None
    dimension_name: str
    source_member: str
    bridge_member: str


def discover_kickout_members(
    *,
    rows: Sequence[ImportedRow],
    dim_names: Sequence[str],
    lookup: dict[tuple[int, str, str], BridgeMapping],
    mappings: Sequence[BridgeMapping],
    app_names: dict[int, str],
    app_number: int | None = None,
    aliases: dict[tuple[int, str], str] | None = None,
) -> list[KickoutMember]:
    """Unmapped (or sentinel) distinct source members — old kickouts tab.

    Apps with no mappings yet are skipped for imported-row discovery.
    Otherwise every distinct imported value would show as a kickout
    before the user uploads a template, which old DART never did.
    """
    seen: set[tuple[int, str, str]] = set()
    out: list[KickoutMember] = []
    apps_with_mappings = {mapping.app_number for mapping in mappings}
    aliases = aliases or {}

    def add(app: int, dimension: str, source: str, bridge: str) -> None:
        if not source:
            return
        if app_number is not None and app != app_number:
            return
        key = (app, dimension.strip().upper(), source)
        if key in seen:
            return
        seen.add(key)
        out.append(
            KickoutMember(
                app_number=app,
                app_name=app_names.get(app),
                dimension_name=dimension.strip().upper(),
                source_member=source,
                bridge_member="" if is_kickout_member(bridge) else bridge,
            )
        )

    for row in rows:
        if row.app_number not in apps_with_mappings:
            continue
        for dim_name in dim_names:
            if is_amount_dimension(dim_name):
                continue
            source = data_value(row.data, dim_name)
            mapping = lookup.get(mapping_key(row.app_number, dim_name, source)) if source else None
            if mapping is None or is_kickout_member(mapping.bridge_member):
                add(
                    row.app_number,
                    dim_name,
                    source,
                    mapping.bridge_member if mapping is not None else "",
                )

    for mapping in mappings:
        if app_number is not None and mapping.app_number != app_number:
            continue
        if not is_kickout_member(mapping.bridge_member):
            continue
        add(
            mapping.app_number,
            canonical_dimension_name(
                mapping.dimension_name, mapping.app_number, aliases
            ),
            mapping.source_member,
            mapping.bridge_member,
        )

    out.sort(key=lambda item: (item.app_number, item.dimension_name, item.source_member))
    return out


async def load_bridged_dimensions(db: AsyncSession, recon_id: uuid.UUID) -> list[str]:
    names = (
        (
            await db.execute(
                select(Dimension.name)
                .where(Dimension.recon_id == recon_id)
                .order_by(Dimension.position)
            )
        )
        .scalars()
        .all()
    )
    return [name for name in names if not is_amount_dimension(name)]


async def load_app_names(db: AsyncSession, recon_id: uuid.UUID) -> dict[int, str]:
    rows = (
        await db.execute(
            select(ReconApp.app_number, ReconApp.name).where(ReconApp.recon_id == recon_id)
        )
    ).all()
    return {int(app_number): name for app_number, name in rows}


async def load_mappings(db: AsyncSession, recon_id: uuid.UUID) -> list[BridgeMapping]:
    return list(
        (
            await db.execute(select(BridgeMapping).where(BridgeMapping.recon_id == recon_id))
        )
        .scalars()
        .all()
    )


async def assert_app_not_signed_off(db: AsyncSession, recon_id: uuid.UUID, app_number: int) -> None:
    signed = (
        await db.execute(
            select(ReportSignoff.id).where(
                ReportSignoff.recon_id == recon_id,
                ReportSignoff.app_number == app_number,
                ReportSignoff.signed_off.is_(True),
            )
        )
    ).scalar_one_or_none()
    if signed is not None:
        raise AppError(
            f"App {app_number} is signed-off. Changes cannot be made.",
            code="recon_signed_off",
        )
