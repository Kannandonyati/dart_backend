"""Save As — clone recon configuration into a new recon owned by the caller."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.bridge import BridgeMapping
from app.models.dimension import Dimension, DimensionMapping, ReconApp
from app.models.recon import Recon
from app.models.security import Group
from app.models.sync import SyncMapping
from app.models.user import User


async def copy_recon(
    db: AsyncSession,
    *,
    source: Recon,
    name: str,
    owner: User,
    group: Group,
) -> Recon:
    clone = Recon(
        name=name,
        description=source.description,
        owner_id=owner.id,
        status="Created",
        archived=False,
    )
    clone.groups.append(group)
    db.add(clone)
    await db.flush()

    apps = (
        (await db.execute(select(ReconApp).where(ReconApp.recon_id == source.id))).scalars().all()
    )
    for app in apps:
        db.add(
            ReconApp(
                recon_id=clone.id,
                app_number=app.app_number,
                name=app.name,
                description=app.description,
                delimiter=app.delimiter,
                currency_delimiter=app.currency_delimiter,
                currency_symbol=app.currency_symbol,
                thousands_separator=app.thousands_separator,
                has_header=app.has_header,
                global_variable_id=app.global_variable_id,
            )
        )

    dimensions = (
        (
            await db.execute(
                select(Dimension)
                .options(selectinload(Dimension.mappings))
                .where(Dimension.recon_id == source.id)
                .order_by(Dimension.position)
            )
        )
        .scalars()
        .all()
    )
    for dimension in dimensions:
        clone_dim = Dimension(recon_id=clone.id, name=dimension.name, position=dimension.position)
        clone_dim.mappings = [
            DimensionMapping(
                app_number=mapping.app_number,
                in_file=mapping.in_file,
                column_location=mapping.column_location,
                default_value=mapping.default_value,
                is_active=mapping.is_active,
            )
            for mapping in dimension.mappings
        ]
        db.add(clone_dim)

    mappings = (
        (await db.execute(select(BridgeMapping).where(BridgeMapping.recon_id == source.id)))
        .scalars()
        .all()
    )
    for mapping in mappings:
        db.add(
            BridgeMapping(
                recon_id=clone.id,
                app_number=mapping.app_number,
                dimension_name=mapping.dimension_name,
                source_member=mapping.source_member,
                bridge_member=mapping.bridge_member,
                flip_sign=mapping.flip_sign,
                dim_comment=mapping.dim_comment,
                bridge_comment=mapping.bridge_comment,
                je_comment=mapping.je_comment,
                is_invalid=mapping.is_invalid,
            )
        )

    syncs = (
        (await db.execute(select(SyncMapping).where(SyncMapping.recon_id == source.id)))
        .scalars()
        .all()
    )
    for mapping in syncs:
        db.add(
            SyncMapping(
                recon_id=clone.id,
                app_number=mapping.app_number,
                dimension_names=list(mapping.dimension_names),
                concat_delimiter=mapping.concat_delimiter,
                source_sync=mapping.source_sync,
                target_sync=mapping.target_sync,
                flip_sign=mapping.flip_sign,
            )
        )

    await db.flush()
    return clone
