"""Team CRUD tests — single-parented to a Lob, unlike Group."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.security import Role
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
LOBS_URL = "/api/v1/lobs"
TEAMS_URL = "/api/v1/teams"


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


async def test_creating_a_team_requires_an_existing_lob(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    response = await client.post(
        TEAMS_URL,
        headers=_auth(token),
        json={"name": "Payroll", "lob_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


async def test_create_team_under_a_lob_and_list_filtered_by_lob(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    lob = await client.post(LOBS_URL, headers=_auth(token), json={"name": "Finance"})
    lob_id = lob.json()["id"]
    other_lob = await client.post(LOBS_URL, headers=_auth(token), json={"name": "Ops"})
    other_lob_id = other_lob.json()["id"]

    created = await client.post(
        TEAMS_URL, headers=_auth(token), json={"name": "Payroll", "lob_id": lob_id}
    )
    assert created.status_code == 201
    body = created.json()
    assert body["lob_name"] == "Finance"

    await client.post(
        TEAMS_URL, headers=_auth(token), json={"name": "Logistics", "lob_id": other_lob_id}
    )

    filtered = await client.get(f"{TEAMS_URL}?lob_id={lob_id}", headers=_auth(token))
    names = [t["name"] for t in filtered.json()]
    assert names == ["Payroll"]


async def test_same_team_name_allowed_in_different_lobs(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    lob_a = (await client.post(LOBS_URL, headers=_auth(token), json={"name": "A"})).json()["id"]
    lob_b = (await client.post(LOBS_URL, headers=_auth(token), json={"name": "B"})).json()["id"]

    first = await client.post(
        TEAMS_URL, headers=_auth(token), json={"name": "Core", "lob_id": lob_a}
    )
    second = await client.post(
        TEAMS_URL, headers=_auth(token), json={"name": "Core", "lob_id": lob_b}
    )
    assert first.status_code == 201
    assert second.status_code == 201


async def test_duplicate_team_name_within_same_lob_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    lob_id = (await client.post(LOBS_URL, headers=_auth(token), json={"name": "Finance"})).json()[
        "id"
    ]

    await client.post(TEAMS_URL, headers=_auth(token), json={"name": "Core", "lob_id": lob_id})
    response = await client.post(
        TEAMS_URL, headers=_auth(token), json={"name": "Core", "lob_id": lob_id}
    )
    assert response.status_code == 409


async def test_creating_a_team_requires_security_manage_privilege(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    admin_token = await _admin_token(client, make_user)
    lob_id = (
        await client.post(LOBS_URL, headers=_auth(admin_token), json={"name": "Finance"})
    ).json()["id"]

    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    response = await client.post(
        TEAMS_URL, headers=_auth(token), json={"name": "Core", "lob_id": lob_id}
    )
    assert response.status_code == 403


async def test_rename_team_and_delete_team(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    lob_id = (await client.post(LOBS_URL, headers=_auth(token), json={"name": "Finance"})).json()[
        "id"
    ]
    team_id = (
        await client.post(TEAMS_URL, headers=_auth(token), json={"name": "Old", "lob_id": lob_id})
    ).json()["id"]

    renamed = await client.patch(
        f"{TEAMS_URL}/{team_id}", headers=_auth(token), json={"name": "New"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "New"

    deleted = await client.delete(f"{TEAMS_URL}/{team_id}", headers=_auth(token))
    assert deleted.status_code == 204

    fetched = await client.get(f"{TEAMS_URL}/{team_id}", headers=_auth(token))
    assert fetched.status_code == 404


async def test_team_lifecycle_is_audited(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], admin_role: Role
) -> None:
    """Same audit coverage as lobs.py — see test_security_lobs.py's
    sibling test."""
    token = await _admin_token(client, make_user)
    member = await make_user(email="m@dart.com", username="member", password="Password123!")

    lob_id = (
        await client.post(LOBS_URL, headers=_auth(token), json={"name": "AuditedLobForTeam"})
    ).json()["id"]
    created = await client.post(
        TEAMS_URL, headers=_auth(token), json={"name": "AuditedTeam", "lob_id": lob_id}
    )
    team_id = created.json()["id"]
    await client.patch(f"{TEAMS_URL}/{team_id}", headers=_auth(token), json={"name": "Renamed"})
    await client.post(
        f"{TEAMS_URL}/{team_id}/members", headers=_auth(token), json={"user_id": str(member.id)}
    )
    await client.delete(f"{TEAMS_URL}/{team_id}/members/{member.id}", headers=_auth(token))
    await client.post(
        f"{TEAMS_URL}/{team_id}/admins", headers=_auth(token), json={"user_id": str(member.id)}
    )
    await client.delete(f"{TEAMS_URL}/{team_id}/admins/{member.id}", headers=_auth(token))
    await client.delete(f"{TEAMS_URL}/{team_id}", headers=_auth(token))

    logs = await client.get("/api/v1/audit-logs/mine", headers=_auth(token))
    actions = [entry["action"] for entry in logs.json()["data"]]
    assert actions == [
        "team.deleted",
        "team.admin_removed",
        "team.admin_added",
        "team.member_removed",
        "team.member_added",
        "team.updated",
        "team.created",
        "lob.created",
        "auth.login",
    ]
