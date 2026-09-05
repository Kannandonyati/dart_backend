"""Group CRUD, admin/member management, and Lob/Team/Role/Recon linking.

The linking tests here are the actual regression coverage for the bug
this phase fixes: Phase 1 originally modeled Group.team_id as a
required single FK; a group is really standalone and many-to-many with
both Lob and Team (see app/models/security.py's module docstring)."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.security import Role
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
LOBS_URL = "/api/v1/lobs"
TEAMS_URL = "/api/v1/teams"
GROUPS_URL = "/api/v1/groups"
ROLES_URL = "/api/v1/roles"
RECONS_URL = "/api/v1/recons"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _admin_token(client: AsyncClient, make_user: Callable[..., Awaitable[User]]) -> str:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    return await _login(client, "admin@dart.com", "Password123!")


async def test_group_is_created_standalone_with_no_parent_required(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    response = await client.post(GROUPS_URL, headers=_auth(token), json={"name": "Recon Team A"})
    assert response.status_code == 201
    assert response.json()["name"] == "Recon Team A"


async def test_group_can_link_to_multiple_lobs_and_multiple_teams(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """This is the actual regression test for the Phase 1 bug: a group
    genuinely many-to-many with Lob/Team, not parented to a single Team."""
    token = await _admin_token(client, make_user)
    group_id = (await client.post(GROUPS_URL, headers=_auth(token), json={"name": "G1"})).json()[
        "id"
    ]
    lob_a = (await client.post(LOBS_URL, headers=_auth(token), json={"name": "A"})).json()["id"]
    lob_b = (await client.post(LOBS_URL, headers=_auth(token), json={"name": "B"})).json()["id"]
    team_a = (
        await client.post(TEAMS_URL, headers=_auth(token), json={"name": "TA", "lob_id": lob_a})
    ).json()["id"]
    team_b = (
        await client.post(TEAMS_URL, headers=_auth(token), json={"name": "TB", "lob_id": lob_b})
    ).json()["id"]

    for lob_id in (lob_a, lob_b):
        link = await client.post(f"{GROUPS_URL}/{group_id}/lobs/{lob_id}", headers=_auth(token))
        assert link.status_code == 204
    for team_id in (team_a, team_b):
        link = await client.post(f"{GROUPS_URL}/{group_id}/teams/{team_id}", headers=_auth(token))
        assert link.status_code == 204

    details = await client.get(f"{GROUPS_URL}/{group_id}/details", headers=_auth(token))
    body = details.json()
    assert sorted(body["lob_names"]) == ["A", "B"]
    assert sorted(body["team_names"]) == ["TA", "TB"]


async def test_unlinking_a_lob_from_one_group_does_not_affect_another_group_sharing_it(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    lob_id = (await client.post(LOBS_URL, headers=_auth(token), json={"name": "Shared"})).json()[
        "id"
    ]
    group_1 = (await client.post(GROUPS_URL, headers=_auth(token), json={"name": "G1"})).json()[
        "id"
    ]
    group_2 = (await client.post(GROUPS_URL, headers=_auth(token), json={"name": "G2"})).json()[
        "id"
    ]

    await client.post(f"{GROUPS_URL}/{group_1}/lobs/{lob_id}", headers=_auth(token))
    await client.post(f"{GROUPS_URL}/{group_2}/lobs/{lob_id}", headers=_auth(token))

    unlink = await client.delete(f"{GROUPS_URL}/{group_1}/lobs/{lob_id}", headers=_auth(token))
    assert unlink.status_code == 204

    g1_details = (await client.get(f"{GROUPS_URL}/{group_1}/details", headers=_auth(token))).json()
    g2_details = (await client.get(f"{GROUPS_URL}/{group_2}/details", headers=_auth(token))).json()
    assert g1_details["lob_names"] == []
    assert g2_details["lob_names"] == ["Shared"]


async def test_role_can_be_linked_to_a_group(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    group_id = (await client.post(GROUPS_URL, headers=_auth(token), json={"name": "G1"})).json()[
        "id"
    ]
    role_id = (
        await client.post(
            ROLES_URL, headers=_auth(token), json={"name": "Reviewer", "privilege_names": []}
        )
    ).json()["id"]

    link = await client.post(f"{GROUPS_URL}/{group_id}/roles/{role_id}", headers=_auth(token))
    assert link.status_code == 204

    details = await client.get(f"{GROUPS_URL}/{group_id}/details", headers=_auth(token))
    assert details.json()["role_names"] == ["Reviewer"]


async def test_duplicate_group_name_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    await client.post(GROUPS_URL, headers=_auth(token), json={"name": "Dup"})
    response = await client.post(GROUPS_URL, headers=_auth(token), json={"name": "Dup"})
    assert response.status_code == 409


async def test_admin_membership_is_distinguished_from_plain_membership(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], admin_role: Role
) -> None:
    token = await _admin_token(client, make_user)
    member = await make_user(email="m@dart.com", username="member", password="Password123!")
    admin_of_group = await make_user(
        email="ga@dart.com", username="groupadmin", password="Password123!"
    )
    group_id = (await client.post(GROUPS_URL, headers=_auth(token), json={"name": "G1"})).json()[
        "id"
    ]

    await client.post(
        f"{GROUPS_URL}/{group_id}/members", headers=_auth(token), json={"user_id": str(member.id)}
    )
    await client.post(
        f"{GROUPS_URL}/{group_id}/admins",
        headers=_auth(token),
        json={"user_id": str(admin_of_group.id)},
    )

    details = (await client.get(f"{GROUPS_URL}/{group_id}/details", headers=_auth(token))).json()
    assert details["member_names"] == ["member"]
    assert details["admin_names"] == ["groupadmin"]


async def test_groups_mine_returns_only_groups_the_caller_belongs_to(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Backs the recon-creation group dropdown — see the old backend's
    get_group_names_list.py (filter: {username: user})."""
    token = await _admin_token(client, make_user)
    member = await make_user(email="m@dart.com", username="member", password="Password123!")
    member_token = await _login(client, "m@dart.com", "Password123!")

    my_group = (await client.post(GROUPS_URL, headers=_auth(token), json={"name": "Mine"})).json()[
        "id"
    ]
    await client.post(GROUPS_URL, headers=_auth(token), json={"name": "NotMine"})
    await client.post(
        f"{GROUPS_URL}/{my_group}/members", headers=_auth(token), json={"user_id": str(member.id)}
    )

    response = await client.get(f"{GROUPS_URL}/mine", headers=_auth(member_token))
    assert response.status_code == 200
    names = [g["name"] for g in response.json()]
    assert names == ["Mine"]


async def test_recon_can_be_linked_and_unlinked_to_a_group(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old-backend equivalent: add_grp_to_rcn.py — a new recon must be
    linked to a group at creation time in the reference frontend."""
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    admin_token = await _admin_token(client, make_user)
    group_id = (
        await client.post(GROUPS_URL, headers=_auth(admin_token), json={"name": "G1"})
    ).json()["id"]

    recon_id = (await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})).json()[
        "id"
    ]

    linked = await client.post(f"{RECONS_URL}/{recon_id}/groups/{group_id}", headers=_auth(token))
    assert linked.status_code == 200
    assert linked.json()["group_name"] == "G1"

    unlinked = await client.delete(
        f"{RECONS_URL}/{recon_id}/groups/{group_id}", headers=_auth(token)
    )
    assert unlinked.status_code == 200
    assert unlinked.json()["group_name"] is None


async def test_linking_a_recon_to_a_nonexistent_group_is_404(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})).json()[
        "id"
    ]

    response = await client.post(
        f"{RECONS_URL}/{recon_id}/groups/00000000-0000-0000-0000-000000000000",
        headers=_auth(token),
    )
    assert response.status_code == 404


async def test_group_lifecycle_is_audited(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], admin_role: Role
) -> None:
    """Same audit coverage as lobs.py/teams.py/roles.py — see
    test_security_lobs.py's sibling test. Group additionally has
    Lob/Team/Role linking, audited the same way as membership changes."""
    token = await _admin_token(client, make_user)
    member = await make_user(email="m@dart.com", username="member", password="Password123!")

    lob_id = (await client.post(LOBS_URL, headers=_auth(token), json={"name": "GLob"})).json()["id"]
    team_id = (
        await client.post(TEAMS_URL, headers=_auth(token), json={"name": "GTeam", "lob_id": lob_id})
    ).json()["id"]
    role_id = (
        await client.post(ROLES_URL, headers=_auth(token), json={"name": "GRole", "privilege_names": []})
    ).json()["id"]

    created = await client.post(GROUPS_URL, headers=_auth(token), json={"name": "AuditedGroup"})
    group_id = created.json()["id"]
    await client.patch(f"{GROUPS_URL}/{group_id}", headers=_auth(token), json={"name": "Renamed"})
    await client.post(
        f"{GROUPS_URL}/{group_id}/members", headers=_auth(token), json={"user_id": str(member.id)}
    )
    await client.delete(f"{GROUPS_URL}/{group_id}/members/{member.id}", headers=_auth(token))
    await client.post(
        f"{GROUPS_URL}/{group_id}/admins", headers=_auth(token), json={"user_id": str(member.id)}
    )
    await client.delete(f"{GROUPS_URL}/{group_id}/admins/{member.id}", headers=_auth(token))
    await client.post(f"{GROUPS_URL}/{group_id}/lobs/{lob_id}", headers=_auth(token))
    await client.delete(f"{GROUPS_URL}/{group_id}/lobs/{lob_id}", headers=_auth(token))
    await client.post(f"{GROUPS_URL}/{group_id}/teams/{team_id}", headers=_auth(token))
    await client.delete(f"{GROUPS_URL}/{group_id}/teams/{team_id}", headers=_auth(token))
    await client.post(f"{GROUPS_URL}/{group_id}/roles/{role_id}", headers=_auth(token))
    await client.delete(f"{GROUPS_URL}/{group_id}/roles/{role_id}", headers=_auth(token))
    await client.delete(f"{GROUPS_URL}/{group_id}", headers=_auth(token))

    logs = await client.get("/api/v1/audit-logs/mine", headers=_auth(token))
    actions = [entry["action"] for entry in logs.json()["data"]]
    assert actions == [
        "group.deleted",
        "group.role_unlinked",
        "group.role_linked",
        "group.team_unlinked",
        "group.team_linked",
        "group.lob_unlinked",
        "group.lob_linked",
        "group.admin_removed",
        "group.admin_added",
        "group.member_removed",
        "group.member_added",
        "group.updated",
        "group.created",
        "role.created",
        "team.created",
        "lob.created",
        "auth.login",
    ]
