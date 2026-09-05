"""Which groups a user can reach — direct membership plus LOB/team inheritance.

Old Dart expanded team → group and LOB → group in
`vw_usr_rcn_grp_details`. Phase 3 deferred that. This is that join,
in one place, so privilege checks and recon access stay aligned.
"""

from uuid import UUID

from sqlalchemy import select

from app.api.deps import DbSession
from app.models.security import Membership, ScopeType, group_lobs, group_teams


async def accessible_group_ids(db: DbSession, user_id: UUID) -> set[UUID]:
    memberships = (
        await db.execute(
            select(Membership.scope_type, Membership.scope_id).where(Membership.user_id == user_id)
        )
    ).all()
    group_ids = {row.scope_id for row in memberships if row.scope_type == ScopeType.GROUP}
    lob_ids = {row.scope_id for row in memberships if row.scope_type == ScopeType.LOB}
    team_ids = {row.scope_id for row in memberships if row.scope_type == ScopeType.TEAM}

    if lob_ids:
        group_ids.update(
            (await db.execute(select(group_lobs.c.group_id).where(group_lobs.c.lob_id.in_(lob_ids))))
            .scalars()
            .all()
        )
    if team_ids:
        group_ids.update(
            (
                await db.execute(
                    select(group_teams.c.group_id).where(group_teams.c.team_id.in_(team_ids))
                )
            )
            .scalars()
            .all()
        )
    return group_ids
