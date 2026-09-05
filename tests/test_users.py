"""User management endpoint tests — the first privilege-gated endpoints,
so this is also where require_privilege's HTTP-layer behavior (403 vs.
401, is_superuser bypass) gets exercised end-to-end rather than just
unit-tested against the bare function (see tests/test_permissions.py)."""

import asyncio
from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


async def test_superuser_can_create_a_user_without_any_explicit_grant(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token = await _login(client, "admin@dart.com", "Password123!")

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "new@dart.com", "username": "newuser", "password": "NewUserPass123!"},
    )
    assert response.status_code == 201
    assert response.json()["email"] == "new@dart.com"


async def test_regular_user_without_privilege_cannot_create_a_user(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="plain@dart.com", username="plain", password="Password123!")
    token = await _login(client, "plain@dart.com", "Password123!")

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "new@dart.com", "username": "newuser", "password": "NewUserPass123!"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "permission_denied"


async def test_user_with_explicit_grant_can_create_a_user(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    grant_privilege: Callable[..., Awaitable[None]],
) -> None:
    user = await make_user(email="manager@dart.com", username="manager", password="Password123!")
    await grant_privilege(user, "user:manage")
    token = await _login(client, "manager@dart.com", "Password123!")

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "new@dart.com", "username": "newuser", "password": "NewUserPass123!"},
    )
    assert response.status_code == 201


async def test_creating_a_user_with_a_duplicate_email_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    await make_user(email="existing@dart.com", username="existing", password="Password123!")
    token = await _login(client, "admin@dart.com", "Password123!")

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "existing@dart.com", "username": "different", "password": "SomePass123!"},
    )
    assert response.status_code == 409


async def test_concurrent_duplicate_creation_never_500s(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Regression test for the check-then-insert race in create_user:
    fire two identical create requests concurrently — the existence
    check alone can't stop both from passing before either commits, so
    this only stays a clean 409 (not a crash) because of the
    IntegrityError catch around db.commit(). See users.py's comment on
    that catch for why the pre-check isn't sufficient by itself."""
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token = await _login(client, "admin@dart.com", "Password123!")
    payload = {"email": "racer@dart.com", "username": "racer", "password": "RacerPass123!"}

    responses = await asyncio.gather(
        client.post("/api/v1/users", headers={"Authorization": f"Bearer {token}"}, json=payload),
        client.post("/api/v1/users", headers={"Authorization": f"Bearer {token}"}, json=payload),
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [201, 409]


async def test_creating_a_user_with_an_all_digit_password_is_rejected_cleanly(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Regression test: this used to 500 ('Object of type ValueError is
    not JSON serializable') instead of returning a clean 422 — see
    app/core/exceptions.py's handle_validation_error fix."""
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token = await _login(client, "admin@dart.com", "Password123!")

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "weak@dart.com", "username": "weakuser", "password": "123456789012"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_creating_a_user_with_a_short_password_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token = await _login(client, "admin@dart.com", "Password123!")

    response = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": "short@dart.com", "username": "shortuser", "password": "Ab1!"},
    )
    assert response.status_code == 422


async def test_list_users_requires_privilege(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="plain@dart.com", username="plain", password="Password123!")
    token = await _login(client, "plain@dart.com", "Password123!")

    response = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


async def test_list_users_returns_real_pagination_totals(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """The frontend's Manage Users page shows "Page X of Y N total" -- with
    a bare-array response it has no way to know N beyond the current page's
    row count. GET /users must report a real total_count computed across
    the whole matching set, not just len(current page)."""
    await make_user(
        email="admin@dart.com", username="admin", password="Password123!", is_superuser=True
    )
    token = await _login(client, "admin@dart.com", "Password123!")
    headers = {"Authorization": f"Bearer {token}"}

    for i in range(3):
        await make_user(email=f"user{i}@dart.com", username=f"user{i}", password="Password123!")

    response = await client.get(
        "/api/v1/users", params={"page": 1, "page_size": 2}, headers=headers
    )
    assert response.status_code == 200
    body = response.json()

    assert len(body["data"]) == 2
    assert body["pagination"]["page"] == 1
    assert body["pagination"]["page_size"] == 2
    # admin + 3 created users = 4 total, regardless of this page's size
    assert body["pagination"]["total_count"] == 4
    assert body["pagination"]["has_more"] is True

    last_page = await client.get(
        "/api/v1/users", params={"page": 2, "page_size": 2}, headers=headers
    )
    assert last_page.json()["pagination"]["has_more"] is False


async def test_any_authenticated_user_can_read_their_own_profile(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="plain@dart.com", username="plain", password="Password123!")
    token = await _login(client, "plain@dart.com", "Password123!")

    response = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == "plain@dart.com"


async def test_update_user_types_and_syncs_is_superuser(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin-types@dart.com",
        username="admintypes",
        password="Password123!",
        is_superuser=True,
    )
    admin_token = await _login(client, "admin-types@dart.com", "Password123!")
    target = await make_user(email="target@dart.com", username="target", password="Password123!")

    granted = await client.patch(
        f"/api/v1/users/{target.id}/user-types",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_types": ["Recon User", "Account Admin"]},
    )
    assert granted.status_code == 200
    body = granted.json()
    # Returned in USER_TYPE_VALUES' canonical order, not submission order.
    assert body["user_types"] == ["Account Admin", "Recon User"]

    target_token = await _login(client, "target@dart.com", "Password123!")
    escalated = await client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {target_token}"}
    )
    assert escalated.status_code == 200  # is_superuser synced True by "Account Admin"

    revoked = await client.patch(
        f"/api/v1/users/{target.id}/user-types",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_types": ["Recon User"]},
    )
    assert revoked.json()["user_types"] == ["Recon User"]

    target_token_2 = await _login(client, "target@dart.com", "Password123!")
    demoted = await client.get(
        "/api/v1/users", headers={"Authorization": f"Bearer {target_token_2}"}
    )
    assert demoted.status_code == 403  # is_superuser synced back False


async def test_update_user_types_rejects_unknown_value(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="admin-types2@dart.com",
        username="admintypes2",
        password="Password123!",
        is_superuser=True,
    )
    admin_token = await _login(client, "admin-types2@dart.com", "Password123!")
    target = await make_user(email="target2@dart.com", username="target2", password="Password123!")

    response = await client.patch(
        f"/api/v1/users/{target.id}/user-types",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_types": ["Made Up Role"]},
    )
    assert response.status_code == 422


async def test_update_user_types_requires_privilege(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="plain-types@dart.com", username="plaintypes", password="Password123!")
    token = await _login(client, "plain-types@dart.com", "Password123!")
    target = await make_user(email="target3@dart.com", username="target3", password="Password123!")

    response = await client.patch(
        f"/api/v1/users/{target.id}/user-types",
        headers={"Authorization": f"Bearer {token}"},
        json={"user_types": ["Recon User"]},
    )
    assert response.status_code == 403


async def test_security_user_types_grant_security_manage(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old Manage Users type flags were authorization, not labels.
    Group Owner / Department Admin / Team Admin must be able to write
    security endpoints the same way account-level security admins could."""
    await make_user(
        email="admin-sec-type@dart.com",
        username="adminsectype",
        password="Password123!",
        is_superuser=True,
    )
    admin_token = await _login(client, "admin-sec-type@dart.com", "Password123!")
    target = await make_user(
        email="teamadmin@dart.com", username="teamadmin", password="Password123!"
    )
    target_token = await _login(client, "teamadmin@dart.com", "Password123!")

    denied = await client.post(
        "/api/v1/lobs",
        headers={"Authorization": f"Bearer {target_token}"},
        json={"name": "Should Fail LOB"},
    )
    assert denied.status_code == 403

    granted = await client.patch(
        f"/api/v1/users/{target.id}/user-types",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_types": ["Team Admin"]},
    )
    assert granted.status_code == 200

    target_token = await _login(client, "teamadmin@dart.com", "Password123!")
    allowed = await client.post(
        "/api/v1/lobs",
        headers={"Authorization": f"Bearer {target_token}"},
        json={"name": "Team Admin LOB"},
    )
    assert allowed.status_code == 201

    await client.patch(
        f"/api/v1/users/{target.id}/user-types",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_types": []},
    )
    target_token = await _login(client, "teamadmin@dart.com", "Password123!")
    revoked = await client.post(
        "/api/v1/lobs",
        headers={"Authorization": f"Bearer {target_token}"},
        json={"name": "Revoked LOB"},
    )
    assert revoked.status_code == 403


async def test_recon_user_type_can_open_a_group_linked_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old recon_user + group membership unlocked the pipeline for that
    recon. Ownership / recon:manage_all stay as they are; this is the
    missing third path."""
    await make_user(
        email="admin-recon-type@dart.com",
        username="adminrecontype",
        password="Password123!",
        is_superuser=True,
    )
    admin_token = await _login(client, "admin-recon-type@dart.com", "Password123!")
    member = await make_user(
        email="reconuser@dart.com", username="reconuser", password="Password123!"
    )

    recon_id = (
        await client.post(
            "/api/v1/recons",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Shared Pipeline Recon"},
        )
    ).json()["id"]
    group_id = (
        await client.post(
            "/api/v1/groups",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Pipeline Group"},
        )
    ).json()["id"]
    await client.post(
        f"/api/v1/recons/{recon_id}/groups/{group_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    await client.post(
        f"/api/v1/groups/{group_id}/members",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_id": str(member.id)},
    )

    member_token = await _login(client, "reconuser@dart.com", "Password123!")
    hidden = await client.get(
        f"/api/v1/recons/{recon_id}", headers={"Authorization": f"Bearer {member_token}"}
    )
    assert hidden.status_code == 404

    await client.patch(
        f"/api/v1/users/{member.id}/user-types",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"user_types": ["Recon User"]},
    )
    member_token = await _login(client, "reconuser@dart.com", "Password123!")
    visible = await client.get(
        f"/api/v1/recons/{recon_id}", headers={"Authorization": f"Bearer {member_token}"}
    )
    assert visible.status_code == 200
    assert visible.json()["name"] == "Shared Pipeline Recon"
