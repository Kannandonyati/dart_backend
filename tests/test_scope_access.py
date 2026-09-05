"""Group-role privileges and LOB/team inheritance — old Dart vw_usr_rcn_grp_details."""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_privilege
from app.core.recon_access import can_manage_recon
from app.models.recon import Recon, recon_group_xref
from app.models.security import (
    Group,
    Lob,
    Membership,
    Privilege,
    Role,
    ScopeType,
    Team,
    group_lobs,
    group_roles,
    group_teams,
)
from app.models.user import User


async def test_group_role_grants_privilege_to_group_member(
    db_session: AsyncSession, make_user: Callable[..., Awaitable[User]]
) -> None:
    user = await make_user()
    privilege = Privilege(name="execute_recon")
    role = Role(name="Runner", privileges=[privilege])
    group = Group(name="Ops")
    db_session.add_all([privilege, role, group])
    await db_session.flush()
    await db_session.execute(group_roles.insert().values(group_id=group.id, role_id=role.id))
    db_session.add(
        Membership(user_id=user.id, scope_type=ScopeType.GROUP, scope_id=group.id, role_id=None)
    )
    await db_session.commit()

    assert await user_has_privilege(db_session, user.id, "execute_recon") is True
    assert await user_has_privilege(db_session, user.id, "delete_recon") is False


async def test_lob_membership_inherits_group_recon_access(
    db_session: AsyncSession, make_user: Callable[..., Awaitable[User]]
) -> None:
    owner = await make_user(email="owner@dart.com", username="owner")
    member = await make_user(email="lobmem@dart.com", username="lobmem")
    member.user_types = ["Recon User"]
    lob = Lob(name="Finance")
    group = Group(name="FinGroup")
    recon = Recon(name="FinRecon", owner_id=owner.id)
    db_session.add_all([lob, group, recon])
    await db_session.flush()
    await db_session.execute(group_lobs.insert().values(group_id=group.id, lob_id=lob.id))
    await db_session.execute(
        recon_group_xref.insert().values(recon_id=recon.id, group_id=group.id)
    )
    db_session.add(
        Membership(user_id=member.id, scope_type=ScopeType.LOB, scope_id=lob.id, role_id=None)
    )
    await db_session.commit()

    assert await can_manage_recon(db_session, member, recon) is True


async def test_team_membership_inherits_group_recon_access(
    db_session: AsyncSession, make_user: Callable[..., Awaitable[User]]
) -> None:
    owner = await make_user(email="owner2@dart.com", username="owner2")
    member = await make_user(email="teamm@dart.com", username="teamm")
    member.user_types = ["Recon User"]
    lob = Lob(name="OpsLob")
    db_session.add(lob)
    await db_session.flush()
    team = Team(name="OpsTeam", lob_id=lob.id)
    group = Group(name="OpsGroup")
    recon = Recon(name="OpsRecon", owner_id=owner.id)
    db_session.add_all([team, group, recon])
    await db_session.flush()
    await db_session.execute(group_teams.insert().values(group_id=group.id, team_id=team.id))
    await db_session.execute(
        recon_group_xref.insert().values(recon_id=recon.id, group_id=group.id)
    )
    db_session.add(
        Membership(user_id=member.id, scope_type=ScopeType.TEAM, scope_id=team.id, role_id=None)
    )
    await db_session.commit()

    assert await can_manage_recon(db_session, member, recon) is True
