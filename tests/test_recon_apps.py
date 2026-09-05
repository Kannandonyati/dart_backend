"""Recon App CRUD tests."""

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


async def _owner_token_and_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> tuple[str, str]:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})).json()[
        "id"
    ]
    return token, recon_id


async def test_new_recon_starts_with_two_apps(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old-backend parity: `f_modify_recon` inserted two
    `recon_application` rows (`app_type` '0' and '1') as part of recon
    creation. Same two slots here, with the placeholder names the
    reference UI used to invent at render time — see
    app/core/recon_bootstrap.py."""
    token, recon_id = await _owner_token_and_recon(client, make_user)

    listed = await client.get(f"{RECONS_URL}/{recon_id}/apps", headers=_auth(token))
    assert listed.status_code == 200
    body = listed.json()
    assert [a["app_number"] for a in body] == [1, 2]
    assert [a["name"] for a in body] == ["App 1", "App 2"]
    assert all(a["delimiter"] == "," for a in body)
    assert all(a["has_header"] is True for a in body)


async def test_create_recon_app_duplicate_number_is_conflict(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """App 1 already exists from create-recon seeding."""
    token, recon_id = await _owner_token_and_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/apps",
        headers=_auth(token),
        json={"app_number": 1, "name": "Duplicate"},
    )
    assert response.status_code == 409


async def test_create_recon_app_invalid_app_number_is_422(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/apps", headers=_auth(token), json={"app_number": 6, "name": "GL"}
    )
    assert response.status_code == 422


async def test_create_third_app_succeeds(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old DART let Dimension Linking add apps up to 5 after the two
    created with the recon."""
    token, recon_id = await _owner_token_and_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/apps",
        headers=_auth(token),
        json={"app_number": 3, "name": "Subledger"},
    )
    assert response.status_code == 201
    listed = await client.get(f"{RECONS_URL}/{recon_id}/apps", headers=_auth(token))
    assert [a["app_number"] for a in listed.json()] == [1, 2, 3]
    dims = await client.get(f"{RECONS_URL}/{recon_id}/dimensions", headers=_auth(token))
    for dimension in dims.json():
        assert {m["app_number"] for m in dimension["mappings"]} == {1, 2, 3}


async def test_non_owner_cannot_see_or_create_recon_apps(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    listed = await client.get(f"{RECONS_URL}/{recon_id}/apps", headers=_auth(token_b))
    assert listed.status_code == 404

    created = await client.post(
        f"{RECONS_URL}/{recon_id}/apps",
        headers=_auth(token_b),
        json={"app_number": 1, "name": "GL"},
    )
    assert created.status_code == 404


async def test_update_recon_app_partial(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    renamed = await client.patch(
        f"{RECONS_URL}/{recon_id}/apps/1", headers=_auth(token), json={"name": "GL"}
    )
    assert renamed.status_code == 200

    updated = await client.patch(
        f"{RECONS_URL}/{recon_id}/apps/1", headers=_auth(token), json={"delimiter": ";"}
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["delimiter"] == ";"
    assert body["name"] == "GL"


async def test_create_apps_up_to_five_then_conflict(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_token_and_recon(client, make_user)
    for app_number, name in ((3, "AppThree"), (4, "AppFour"), (5, "AppFive")):
        created = await client.post(
            f"{RECONS_URL}/{recon_id}/apps",
            headers=_auth(token),
            json={"app_number": app_number, "name": name},
        )
        assert created.status_code == 201, created.text
    sixth = await client.post(
        f"{RECONS_URL}/{recon_id}/apps",
        headers=_auth(token),
        json={"app_number": 5, "name": "AppSix"},
    )
    assert sixth.status_code == 409
    assert "Maximum" in sixth.json()["error"]["message"]


async def test_update_nonexistent_recon_app_is_404(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """App 3 is not created with the recon, so PATCH is 404 until Add
    Application has run for that slot."""
    token, recon_id = await _owner_token_and_recon(client, make_user)
    response = await client.patch(
        f"{RECONS_URL}/{recon_id}/apps/3", headers=_auth(token), json={"delimiter": ";"}
    )
    assert response.status_code == 404
