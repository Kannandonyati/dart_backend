"""Recon core endpoint tests. Access-model tests mirror the "never 403,
always 404 for not-found-or-not-yours" rule from app/api/v1/endpoints/
recons.py's module docstring — every one of those cases gets its own
assertion here, not just the happy path."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
RECONS_URL = "/api/v1/recons"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_any_authenticated_user_can_create_a_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    response = await client.post(
        RECONS_URL, headers=_auth(token), json={"name": "Recon One", "description": "desc"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Recon One"
    assert body["owner"] == "a"
    assert body["group_name"] is None
    assert body["archived"] is False


async def test_create_recon_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(RECONS_URL, json={"name": "No Auth Recon"})
    assert response.status_code == 401


async def test_duplicate_recon_name_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    await client.post(RECONS_URL, headers=_auth(token), json={"name": "Dup"})
    response = await client.post(RECONS_URL, headers=_auth(token), json={"name": "Dup"})
    assert response.status_code == 409


async def test_concurrent_duplicate_recon_creation_never_500s(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    responses = await asyncio.gather(
        client.post(RECONS_URL, headers=_auth(token), json={"name": "Racer"}),
        client.post(RECONS_URL, headers=_auth(token), json={"name": "Racer"}),
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201, 409]


async def test_list_my_recons_only_shows_own_recons(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_a = await _login(client, "a@dart.com", "Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    await client.post(RECONS_URL, headers=_auth(token_a), json={"name": "A's Recon"})
    await client.post(RECONS_URL, headers=_auth(token_b), json={"name": "B's Recon"})

    response = await client.get(RECONS_URL, headers=_auth(token_a))
    names = [r["name"] for r in response.json()]
    assert names == ["A's Recon"]


async def test_owner_can_get_their_own_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token), json={"name": "Mine"})
    recon_id = created.json()["id"]

    response = await client.get(f"{RECONS_URL}/{recon_id}", headers=_auth(token))
    assert response.status_code == 200
    assert response.json()["name"] == "Mine"


async def test_non_owner_gets_404_not_403_for_someone_elses_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """A 403 would confirm the recon exists to a user who otherwise has
    no way to know that — see recons.py's module docstring."""
    await make_user(email="a@dart.com", username="a", password="Password123!")
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_a = await _login(client, "a@dart.com", "Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token_a), json={"name": "A's Recon"})
    recon_id = created.json()["id"]

    response = await client.get(f"{RECONS_URL}/{recon_id}", headers=_auth(token_b))
    assert response.status_code == 404


async def test_superuser_can_get_any_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token_a = await _login(client, "a@dart.com", "Password123!")
    token_admin = await _login(client, "admin@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token_a), json={"name": "A's Recon"})
    recon_id = created.json()["id"]

    response = await client.get(f"{RECONS_URL}/{recon_id}", headers=_auth(token_admin))
    assert response.status_code == 200


async def test_user_with_recon_manage_all_privilege_can_get_any_recon(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    grant_privilege: Callable[..., Awaitable[None]],
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    manager = await make_user(email="mgr@dart.com", username="mgr", password="Password123!")
    await grant_privilege(manager, "recon:manage_all")
    token_a = await _login(client, "a@dart.com", "Password123!")
    token_mgr = await _login(client, "mgr@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token_a), json={"name": "A's Recon"})
    recon_id = created.json()["id"]

    response = await client.get(f"{RECONS_URL}/{recon_id}", headers=_auth(token_mgr))
    assert response.status_code == 200


async def test_owner_can_rename_their_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token), json={"name": "Old Name"})
    recon_id = created.json()["id"]

    response = await client.patch(
        f"{RECONS_URL}/{recon_id}", headers=_auth(token), json={"name": "New Name"}
    )
    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


async def test_non_owner_cannot_rename_someone_elses_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_a = await _login(client, "a@dart.com", "Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token_a), json={"name": "A's Recon"})
    recon_id = created.json()["id"]

    response = await client.patch(
        f"{RECONS_URL}/{recon_id}", headers=_auth(token_b), json={"name": "Hijacked"}
    )
    assert response.status_code == 404


async def test_delete_is_soft_and_hides_from_list_and_get(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token), json={"name": "To Delete"})
    recon_id = created.json()["id"]

    delete_response = await client.delete(f"{RECONS_URL}/{recon_id}", headers=_auth(token))
    assert delete_response.status_code == 204

    get_response = await client.get(f"{RECONS_URL}/{recon_id}", headers=_auth(token))
    assert get_response.status_code == 404

    list_response = await client.get(RECONS_URL, headers=_auth(token))
    assert list_response.json() == []


async def test_deleted_recon_name_can_be_reused(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Delete is soft, so the row stays — but uniqueness is among *live*
    recons only. Recreating the same name after delete must succeed,
    otherwise the Select screen's empty list and the create form
    contradict each other."""
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token), json={"name": "Test_recon"})
    assert created.status_code == 201
    recon_id = created.json()["id"]

    deleted = await client.delete(f"{RECONS_URL}/{recon_id}", headers=_auth(token))
    assert deleted.status_code == 204

    recreated = await client.post(RECONS_URL, headers=_auth(token), json={"name": "Test_recon"})
    assert recreated.status_code == 201
    assert recreated.json()["name"] == "Test_recon"
    assert recreated.json()["id"] != recon_id


async def test_rename_onto_a_deleted_recon_name_is_allowed(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")

    first = await client.post(RECONS_URL, headers=_auth(token), json={"name": "Taken"})
    await client.delete(f"{RECONS_URL}/{first.json()['id']}", headers=_auth(token))
    second = await client.post(RECONS_URL, headers=_auth(token), json={"name": "Other"})
    renamed = await client.patch(
        f"{RECONS_URL}/{second.json()['id']}",
        headers=_auth(token),
        json={"name": "Taken"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Taken"


async def test_non_owner_cannot_delete_someone_elses_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_a = await _login(client, "a@dart.com", "Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token_a), json={"name": "A's Recon"})
    recon_id = created.json()["id"]

    response = await client.delete(f"{RECONS_URL}/{recon_id}", headers=_auth(token_b))
    assert response.status_code == 404

    # Confirm it's genuinely still there for the owner — the failed
    # delete attempt from a non-owner must not have silently succeeded.
    get_response = await client.get(f"{RECONS_URL}/{recon_id}", headers=_auth(token_a))
    assert get_response.status_code == 200


async def test_list_available_is_empty_until_group_linking_exists(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Phase 3 adds the endpoints that create recon_group_xref rows —
    until then this always returns empty, correctly, not an error."""
    await make_user(email="a@dart.com", username="a", password="Password123!")
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_a = await _login(client, "a@dart.com", "Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    await client.post(RECONS_URL, headers=_auth(token_a), json={"name": "A's Recon"})

    response = await client.get(f"{RECONS_URL}/available", headers=_auth(token_b))
    assert response.status_code == 200
    assert response.json() == []


async def test_response_never_leaks_recon_id_of_nonexistent_recon_differently(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """A genuinely nonexistent recon id and an existing-but-forbidden one
    must be indistinguishable to the caller."""
    await make_user(email="a@dart.com", username="a", password="Password123!")
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_a = await _login(client, "a@dart.com", "Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    created = await client.post(RECONS_URL, headers=_auth(token_a), json={"name": "A's Recon"})
    real_id = created.json()["id"]
    fake_id = str(uuid.uuid4())

    real_response = await client.get(f"{RECONS_URL}/{real_id}", headers=_auth(token_b))
    fake_response = await client.get(f"{RECONS_URL}/{fake_id}", headers=_auth(token_b))

    assert real_response.status_code == fake_response.status_code == 404
    real_error = real_response.json()["error"]
    fake_error = fake_response.json()["error"]
    assert real_error["code"] == fake_error["code"] == "not_found"
    assert real_error["message"] == fake_error["message"]
