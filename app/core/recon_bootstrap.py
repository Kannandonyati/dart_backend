"""What a brand-new recon starts life with: two applications and the
three mandatory dimensions.

This is the API-layer home of work the old backend split across two
places. The two `recon_application` rows were created inside the
`f_modify_recon` stored procedure (`FOR i IN 0..1`, one row per
`app_type` `'0'`/`'1'`), while YEAR/PERIOD/AMOUNT were seeded by the
*frontend* firing three `dim_linking/update` calls right after
`recon/create` returned (`InitialiseReconDimension` / `initvalues.js`).

Both now happen in `create_recon`, inside its transaction, which closes
the hole the old split left: a create that succeeded followed by a
failed seed left a recon with no mandatory dimensions and no way to
notice.

The old backend created the app rows bare — no `recon_app_setting`, so
the reference UI displayed the placeholder "App1"/"App2" until the user
filled in a name. `ReconApp.name` is non-nullable here, so the
placeholder is stored as the initial name instead of being invented at
render time.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.recon_limits import BOOTSTRAP_APP_NUMBERS
from app.models.dimension import (
    MANDATORY_DIMENSION_NAMES,
    Dimension,
    DimensionMapping,
    ReconApp,
)

DEFAULT_APP_NUMBERS = BOOTSTRAP_APP_NUMBERS


def _mandatory_dimension(recon_id: uuid.UUID, name: str, position: int) -> Dimension:
    """A mandatory dimension mapped for both apps, left "not in file"
    with an empty default so the user still points it at the real
    column. Matches the values the old frontend's seed payload sent."""
    return Dimension(
        recon_id=recon_id,
        name=name,
        position=position,
        mappings=[
            DimensionMapping(app_number=app_number, in_file=False, default_value="", is_active=True)
            for app_number in DEFAULT_APP_NUMBERS
        ],
    )


async def seed_mandatory_dimensions(db: AsyncSession, recon_id: uuid.UUID) -> None:
    """Adds whichever of YEAR/PERIOD/AMOUNT the recon is missing,
    appended after whatever's already there. Idempotent, and does not
    commit — the caller owns the transaction."""
    existing = (
        (await db.execute(select(Dimension).where(Dimension.recon_id == recon_id))).scalars().all()
    )
    existing_names = {dimension.name for dimension in existing}
    next_position = len(existing)

    for name in MANDATORY_DIMENSION_NAMES:
        if name in existing_names:
            continue
        db.add(_mandatory_dimension(recon_id, name, next_position))
        next_position += 1


async def seed_new_recon(db: AsyncSession, recon_id: uuid.UUID) -> None:
    """Gives a just-created recon its two application slots and the
    three mandatory dimensions. Called from `create_recon` before its
    commit, so a recon never exists without them."""
    for app_number in DEFAULT_APP_NUMBERS:
        db.add(
            ReconApp(
                recon_id=recon_id,
                app_number=app_number,
                name=f"App {app_number}",
            )
        )
    await db.flush()
    await seed_mandatory_dimensions(db, recon_id)
