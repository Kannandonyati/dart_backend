"""Sync Mapping CRUD, possible-combinations, and sync-data run tests."""

import uuid
from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.user import User
from app.tasks.import_tasks import _run_import
from tests.recon_setup import configure_dimensions

LOGIN_URL = "/api/v1/auth/login"
RECONS_URL = "/api/v1/recons"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _owner_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> tuple[str, str]:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (
        await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})
    ).json()["id"]
    return token, recon_id


async def test_create_and_list_sync_mapping(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/sync-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_names": ["ACCOUNT"],
            "source_sync": "1000",
            "target_sync": "CASH",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["dimension_names"] == ["ACCOUNT"]
    assert body["concat_delimiter"] == "-"

    listed = await client.get(f"{RECONS_URL}/{recon_id}/sync-mappings", headers=_auth(token))
    assert len(listed.json()) == 1


async def test_concat_dimension_mapping(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/sync-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_names": ["ACCOUNT", "COST_CENTER"],
            "concat_delimiter": "|",
            "source_sync": "1000|CC1",
            "target_sync": "CASH_CC1",
        },
    )
    assert response.status_code == 201
    assert response.json()["dimension_names"] == ["ACCOUNT", "COST_CENTER"]


async def test_amount_cannot_be_sync_mapped(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/sync-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_names": ["AMOUNT"],
            "source_sync": "100",
            "target_sync": "X",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_syncable"


async def test_duplicate_sync_mapping_key_is_conflict(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    body = {
        "app_number": 1,
        "dimension_names": ["ACCOUNT"],
        "source_sync": "1000",
        "target_sync": "CASH",
    }
    await client.post(f"{RECONS_URL}/{recon_id}/sync-mappings", headers=_auth(token), json=body)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/sync-mappings", headers=_auth(token), json=body
    )
    assert response.status_code == 409


async def test_update_and_delete_sync_mapping(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        f"{RECONS_URL}/{recon_id}/sync-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_names": ["ACCOUNT"],
            "source_sync": "1000",
            "target_sync": "CASH",
        },
    )
    mapping_id = created.json()["id"]

    updated = await client.patch(
        f"{RECONS_URL}/{recon_id}/sync-mappings/{mapping_id}",
        headers=_auth(token),
        json={"target_sync": "CASH_V2", "flip_sign": True},
    )
    assert updated.status_code == 200
    assert updated.json()["target_sync"] == "CASH_V2"
    assert updated.json()["flip_sign"] is True

    deleted = await client.delete(
        f"{RECONS_URL}/{recon_id}/sync-mappings/{mapping_id}", headers=_auth(token)
    )
    assert deleted.status_code == 204


async def _recon_with_two_apps_dimensions_and_data(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> tuple[str, str]:
    token, recon_id = await _owner_recon(client, make_user)
    await configure_dimensions(
        client,
        token,
        recon_id,
        [("YEAR", "1"), ("ACCOUNT", "2"), ("COST_CENTER", "3"), ("AMOUNT", "4"), ("PERIOD", "5")],
    )
    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={
            "file": (
                "d.csv",
                b"YEAR,ACCOUNT,COST_CENTER,AMOUNT,PERIOD\r\n"
                b"2024,1000,CC1,100,01\r\n"
                b"2024,2000,CC2,200,01\r\n",
                "text/csv",
            )
        },
    )
    await _run_import(uuid.UUID(uploaded.json()["id"]))
    return token, recon_id


async def test_possible_combinations_zips_not_products(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _recon_with_two_apps_dimensions_and_data(client, make_user)

    response = await client.get(
        f"{RECONS_URL}/{recon_id}/sync-mappings/possible-combinations"
        "?app_number=1&dimension_names=ACCOUNT&dimension_names=COST_CENTER",
        headers=_auth(token),
    )
    assert response.status_code == 200
    combos = response.json()
    # Two distinct ACCOUNT values, two distinct COST_CENTER values —
    # zip pairs them positionally (2 combos), NOT a 2x2 cross product
    # (4 combos).
    assert len(combos) == 2
    assert all(len(c) == 2 for c in combos)


async def test_run_transformation_resolves_synced_values(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _recon_with_two_apps_dimensions_and_data(client, make_user)
    await client.post(
        f"{RECONS_URL}/{recon_id}/sync-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_names": ["ACCOUNT"],
            "source_sync": "1000",
            "target_sync": "CASH",
        },
    )

    response = await client.post(f"{RECONS_URL}/{recon_id}/sync-data/run", headers=_auth(token))
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    mapped_row = next(r for r in rows if r["data"]["ACCOUNT"] == "1000")
    unmapped_row = next(r for r in rows if r["data"]["ACCOUNT"] == "2000")
    assert mapped_row["synced"] == {"ACCOUNT": "CASH"}
    assert unmapped_row["synced"] == {}


async def test_run_transformation_resolves_concat_mapping(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _recon_with_two_apps_dimensions_and_data(client, make_user)
    await client.post(
        f"{RECONS_URL}/{recon_id}/sync-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_names": ["ACCOUNT", "COST_CENTER"],
            "concat_delimiter": "|",
            "source_sync": "1000|CC1",
            "target_sync": "CASH_CC1",
        },
    )

    response = await client.post(f"{RECONS_URL}/{recon_id}/sync-data/run", headers=_auth(token))
    rows = response.json()
    mapped_row = next(r for r in rows if r["data"]["ACCOUNT"] == "1000")
    assert mapped_row["synced"] == {"ACCOUNT-COST_CENTER": "CASH_CC1"}


async def test_non_owner_cannot_manage_sync_mappings(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    response = await client.get(f"{RECONS_URL}/{recon_id}/sync-mappings", headers=_auth(token_b))
    assert response.status_code == 404
