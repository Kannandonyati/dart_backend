"""LOB CRUD + admin/member management tests."""

import asyncio
from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.security import Role
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
LOBS_URL = "/api/v1/lobs"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_creating_a_lob_requires_security_manage_privilege(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    response = await client.post(LOBS_URL, headers=_auth(token), json={"name": "Finance"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_creating_a_lob_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(LOBS_URL, json={"name": "Finance"})
    assert response.status_code == 401


async def test_superuser_can_create_and_list_a_lob(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token = await _login(client, "admin@dart.com", "Password123!")

    created = await client.post(LOBS_URL, headers=_auth(token), json={"name": "Finance"})
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Finance"
    assert body["created_by"] == "admin"

    listed = await client.get(LOBS_URL, headers=_auth(token))
    assert any(lob["name"] == "Finance" for lob in listed.json())


async def test_duplicate_lob_name_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token = await _login(client, "admin@dart.com", "Password123!")

    await client.post(LOBS_URL, headers=_auth(token), json={"name": "Finance"})
    response = await client.post(LOBS_URL, headers=_auth(token), json={"name": "Finance"})
    assert response.status_code == 409


async def test_concurrent_duplicate_lob_creation_never_500s(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token = await _login(client, "admin@dart.com", "Password123!")

    responses = await asyncio.gather(
        client.post(LOBS_URL, headers=_auth(token), json={"name": "Racer"}),
        client.post(LOBS_URL, headers=_auth(token), json={"name": "Racer"}),
    )
    assert sorted(r.status_code for r in responses) == [201, 409]


async def test_get_nonexistent_lob_is_404(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    response = await client.get(
        f"{LOBS_URL}/00000000-0000-0000-0000-000000000000", headers=_auth(token)
    )
    assert response.status_code == 404


async def test_admin_and_member_lists_are_separate(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], admin_role: Role
) -> None:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    plain = await make_user(email="p@dart.com", username="plain", password="Password123!")
    lob_admin_candidate = await make_user(
        email="la@dart.com", username="lobadmin", password="Password123!"
    )
    token = await _login(client, "admin@dart.com", "Password123!")

    created = await client.post(LOBS_URL, headers=_auth(token), json={"name": "Ops"})
    lob_id = created.json()["id"]

    add_member = await client.post(
        f"{LOBS_URL}/{lob_id}/members", headers=_auth(token), json={"user_id": str(plain.id)}
    )
    assert add_member.status_code == 204

    add_admin = await client.post(
        f"{LOBS_URL}/{lob_id}/admins",
        headers=_auth(token),
        json={"user_id": str(lob_admin_candidate.id)},
    )
    assert add_admin.status_code == 204

    members = await client.get(f"{LOBS_URL}/{lob_id}/members", headers=_auth(token))
    admins = await client.get(f"{LOBS_URL}/{lob_id}/admins", headers=_auth(token))
    assert members.json() == ["plain"]
    assert admins.json() == ["lobadmin"]

    remove_member = await client.delete(
        f"{LOBS_URL}/{lob_id}/members/{plain.id}", headers=_auth(token)
    )
    assert remove_member.status_code == 204
    members_after = await client.get(f"{LOBS_URL}/{lob_id}/members", headers=_auth(token))
    assert members_after.json() == []


async def test_lob_lifecycle_is_audited(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], admin_role: Role
) -> None:
    """Manage Recon Security is thematically the same "who can do what"
    surface as Manage Users — extends the audit trail (already wired into
    recons.py/report_data.py/user_maintenance.py) to LOB CRUD and
    membership changes, the same lifecycle shape as
    test_recon_lifecycle_is_audited."""
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    member = await make_user(email="m@dart.com", username="member", password="Password123!")
    token = await _login(client, "admin@dart.com", "Password123!")

    created = await client.post(LOBS_URL, headers=_auth(token), json={"name": "AuditedLob"})
    lob_id = created.json()["id"]
    await client.patch(f"{LOBS_URL}/{lob_id}", headers=_auth(token), json={"name": "RenamedLob"})
    await client.post(
        f"{LOBS_URL}/{lob_id}/members", headers=_auth(token), json={"user_id": str(member.id)}
    )
    await client.delete(f"{LOBS_URL}/{lob_id}/members/{member.id}", headers=_auth(token))
    await client.post(
        f"{LOBS_URL}/{lob_id}/admins", headers=_auth(token), json={"user_id": str(member.id)}
    )
    await client.delete(f"{LOBS_URL}/{lob_id}/admins/{member.id}", headers=_auth(token))
    await client.delete(f"{LOBS_URL}/{lob_id}", headers=_auth(token))

    logs = await client.get("/api/v1/audit-logs/mine", headers=_auth(token))
    actions = [entry["action"] for entry in logs.json()["data"]]
    assert actions == [
        "lob.deleted",
        "lob.admin_removed",
        "lob.admin_added",
        "lob.member_removed",
        "lob.member_added",
        "lob.updated",
        "lob.created",
        "auth.login",
    ]


async def test_adding_same_member_twice_is_a_clean_conflict_not_500(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    plain = await make_user(email="p@dart.com", username="plain", password="Password123!")
    token = await _login(client, "admin@dart.com", "Password123!")

    created = await client.post(LOBS_URL, headers=_auth(token), json={"name": "Ops"})
    lob_id = created.json()["id"]

    first = await client.post(
        f"{LOBS_URL}/{lob_id}/members", headers=_auth(token), json={"user_id": str(plain.id)}
    )
    second = await client.post(
        f"{LOBS_URL}/{lob_id}/members", headers=_auth(token), json={"user_id": str(plain.id)}
    )
    assert first.status_code == 204
    assert second.status_code == 409
