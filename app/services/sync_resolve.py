"""Transformation resolve — old dart-db `f_create_tfn_sync` / override join.

Maps concatenated source members (bridged when present, else imported)
through `SyncMapping` to `target_sync`, then applies `flip_sign` on top of
the already bridge-adjusted amount.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.services.bridge_resolve import (
    data_value,
    format_decimal,
    is_kickout_member,
    parse_amount,
)


class SyncMappingLike(Protocol):
    app_number: int
    dimension_names: list[str]
    concat_delimiter: str
    source_sync: str
    target_sync: str
    flip_sign: bool


@dataclass(frozen=True)
class SyncedResolution:
    synced: dict[str, str]
    amount: str
    sign_reversed_amount: str
    flip_sign: bool


def sync_source_value(dim_name: str, data: dict[str, str], resolved: dict[str, str]) -> str:
    bridged = (resolved.get(dim_name) or "").strip()
    if bridged and not is_kickout_member(bridged):
        return bridged
    return data_value(data, dim_name)


def zip_distinct_lists(value_lists: Sequence[Sequence[str]], *, delimiter: str) -> list[str]:
    """Old `generate_combinations`: positional zip, not a cross product."""
    if not value_lists:
        return []
    combos: list[str] = []
    for parts in zip(*value_lists, strict=False):
        if any(not part for part in parts):
            continue
        combos.append(delimiter.join(parts))
    return combos


def apply_sync_mappings(
    *,
    app_number: int,
    data: dict[str, str],
    resolved: dict[str, str],
    mappings: Sequence[SyncMappingLike],
    amount: str,
    sign_reversed_amount: str,
) -> SyncedResolution:
    synced: dict[str, str] = {}
    extra_sign = Decimal("1")
    matched_flip = False
    for mapping in mappings:
        if mapping.app_number != app_number:
            continue
        values = [sync_source_value(name, data, resolved) for name in mapping.dimension_names]
        if any(not value for value in values):
            continue
        if mapping.concat_delimiter.join(values) != mapping.source_sync:
            continue
        synced["-".join(mapping.dimension_names)] = mapping.target_sync
        if mapping.flip_sign:
            extra_sign *= Decimal("-1")
            matched_flip = True
    return SyncedResolution(
        synced=synced,
        amount=format_decimal(parse_amount(amount)),
        sign_reversed_amount=format_decimal(parse_amount(sign_reversed_amount) * extra_sign),
        flip_sign=matched_flip,
    )
