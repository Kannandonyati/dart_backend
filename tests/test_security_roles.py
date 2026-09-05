"""Role CRUD, including the closed-privilege-catalog rule: privilege_names
must reference existing Privilege rows — no free-text, no silent
auto-creation."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.security import Privilege
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
ROLES_URL = "/api/v1/roles"


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


async def test_create_role_with_no_privileges(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    response = await client.post(
        ROLES_URL, headers=_auth(token), json={"name": "Viewer", "privilege_names": []}
    )
    assert response.status_code == 201
    assert response.json()["privileges"] == []


async def test_create_role_with_real_privileges(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], db_session
) -> None:
    token = await _admin_token(client, make_user)
    db_session.add_all([Privilege(name="create_recon"), Privilege(name="read_recon")])
    await db_session.commit()

    response = await client.post(
        ROLES_URL,
        headers=_auth(token),
        json={"name": "Editor", "privilege_names": ["create_recon", "read_recon"]},
    )
    assert response.status_code == 201
    assert sorted(response.json()["privileges"]) == ["create_recon", "read_recon"]


async def test_create_role_with_unknown_privilege_name_is_a_clean_400_not_a_silent_no_op(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    response = await client.post(
        ROLES_URL,
        headers=_auth(token),
        json={"name": "Ghost", "privilege_names": ["totally_made_up_privilege"]},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unknown_privilege"

    listed = await client.get(ROLES_URL, headers=_auth(token))
    assert not any(r["name"] == "Ghost" for r in listed.json())


async def test_creating_a_role_requires_security_manage_privilege(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    response = await client.post(
        ROLES_URL, headers=_auth(token), json={"name": "Viewer", "privilege_names": []}
    )
    assert response.status_code == 403


async def test_update_role_replaces_privilege_set(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], db_session
) -> None:
    token = await _admin_token(client, make_user)
    db_session.add_all([Privilege(name="create_recon"), Privilege(name="delete_recon")])
    await db_session.commit()

    role_id = (
        await client.post(
            ROLES_URL, headers=_auth(token), json={"name": "R", "privilege_names": ["create_recon"]}
        )
    ).json()["id"]

    updated = await client.patch(
        f"{ROLES_URL}/{role_id}",
        headers=_auth(token),
        json={"privilege_names": ["delete_recon"]},
    )
    assert updated.status_code == 200
    assert updated.json()["privileges"] == ["delete_recon"]


async def test_duplicate_role_name_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin_token(client, make_user)
    await client.post(ROLES_URL, headers=_auth(token), json={"name": "Dup", "privilege_names": []})
    response = await client.post(
        ROLES_URL, headers=_auth(token), json={"name": "Dup", "privilege_names": []}
    )
    assert response.status_code == 409


async def test_delete_role(client: AsyncClient, make_user: Callable[..., Awaitable[User]]) -> None:
    token = await _admin_token(client, make_user)
    role_id = (
        await client.post(
            ROLES_URL, headers=_auth(token), json={"name": "Temp", "privilege_names": []}
        )
    ).json()["id"]

    deleted = await client.delete(f"{ROLES_URL}/{role_id}", headers=_auth(token))
    assert deleted.status_code == 204

    fetched = await client.get(f"{ROLES_URL}/{role_id}", headers=_auth(token))
    assert fetched.status_code == 404


async def test_role_lifecycle_is_audited(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Same audit coverage as lobs.py/teams.py — see test_security_lobs.py's
    sibling test."""
    token = await _admin_token(client, make_user)

    created = await client.post(
        ROLES_URL, headers=_auth(token), json={"name": "AuditedRole", "privilege_names": []}
    )
    role_id = created.json()["id"]
    await client.patch(f"{ROLES_URL}/{role_id}", headers=_auth(token), json={"name": "Renamed"})
    await client.delete(f"{ROLES_URL}/{role_id}", headers=_auth(token))

    logs = await client.get("/api/v1/audit-logs/mine", headers=_auth(token))
    actions = [entry["action"] for entry in logs.json()["data"]]
    assert actions == ["role.deleted", "role.updated", "role.created", "auth.login"]
