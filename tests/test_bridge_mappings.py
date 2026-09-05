"""Bridge Mapping CRUD, default seeding, and CSV import tests."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.user import User
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
    recon_id = (await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})).json()[
        "id"
    ]
    return token, recon_id


async def test_create_and_list_bridge_mapping(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "ACCOUNT",
            "source_member": "1000",
            "bridge_member": "CASH",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["bridge_member"] == "CASH"
    assert body["is_kickout"] is False
    assert body["app_type"] == "App1"
    assert body["is_invalid"] is False
    assert body["je_comment"] is None
    assert body["dim_comment"] is None

    listed = await client.get(f"{RECONS_URL}/{recon_id}/bridge-mappings", headers=_auth(token))
    assert len(listed.json()) == 1


async def test_amount_dimension_cannot_be_mapped(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "AMOUNT",
            "source_member": "1000",
            "bridge_member": "X",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "not_bridgeable"


async def test_duplicate_mapping_key_is_conflict(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    body = {
        "app_number": 1,
        "dimension_name": "ACCOUNT",
        "source_member": "1000",
        "bridge_member": "CASH",
    }
    await client.post(f"{RECONS_URL}/{recon_id}/bridge-mappings", headers=_auth(token), json=body)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings", headers=_auth(token), json=body
    )
    assert response.status_code == 409


async def test_kickout_sentinel_is_reported_as_is_kickout(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "ACCOUNT",
            "source_member": "9999",
            "bridge_member": "Kickout",
        },
    )
    assert response.json()["is_kickout"] is True


async def test_update_and_delete_bridge_mapping(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "ACCOUNT",
            "source_member": "1000",
            "bridge_member": "CASH",
        },
    )
    mapping_id = created.json()["id"]

    updated = await client.patch(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/{mapping_id}",
        headers=_auth(token),
        json={"bridge_member": "CASH_EQUIV"},
    )
    assert updated.status_code == 200
    assert updated.json()["bridge_member"] == "CASH_EQUIV"

    deleted = await client.delete(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/{mapping_id}", headers=_auth(token)
    )
    assert deleted.status_code == 204


async def test_default_bridge_mappings_creates_identity_mappings_from_imported_data(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    await configure_dimensions(
        client,
        token,
        recon_id,
        [("YEAR", "1"), ("ACCOUNT", "2"), ("AMOUNT", "3"), ("PERIOD", "4")],
    )
    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("d.csv", b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,1000,50,01\r\n", "text/csv")},
    )
    run_id = uploaded.json()["id"]
    import uuid as uuid_module

    from app.tasks.import_tasks import _run_import

    await _run_import(uuid_module.UUID(run_id))

    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/default?app_number=1", headers=_auth(token)
    )
    assert response.status_code == 200
    body = response.json()
    dims_mapped = {m["dimension_name"] for m in body}
    assert dims_mapped == {"YEAR", "PERIOD", "ACCOUNT"}
    # AMOUNT is the measure being reconciled, never bridge-mapped.
    assert "AMOUNT" not in dims_mapped
    account_mapping = next(m for m in body if m["dimension_name"] == "ACCOUNT")
    assert account_mapping["source_member"] == account_mapping["bridge_member"] == "1000"


async def test_default_bridge_mappings_replaces_that_app(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old `f_create_default_bridge` wipes the app then identity-inserts."""
    token, recon_id = await _owner_recon(client, make_user)
    await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "ACCOUNT",
            "source_member": "1000",
            "bridge_member": "REAL_MAPPING",
        },
    )
    await configure_dimensions(
        client,
        token,
        recon_id,
        [("YEAR", "1"), ("ACCOUNT", "2"), ("AMOUNT", "3"), ("PERIOD", "4")],
    )
    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("d.csv", b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,1000,50,01\r\n", "text/csv")},
    )
    run_id = uploaded.json()["id"]
    import uuid as uuid_module

    from app.tasks.import_tasks import _run_import

    await _run_import(uuid_module.UUID(run_id))

    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/default?app_number=1", headers=_auth(token)
    )
    assert response.status_code == 200
    listed = (
        await client.get(
            f"{RECONS_URL}/{recon_id}/bridge-mappings?page_size=50", headers=_auth(token)
        )
    ).json()
    account = next(m for m in listed if m["dimension_name"] == "ACCOUNT")
    assert account["bridge_member"] == "1000"
    assert account["source_member"] == "1000"
    assert not any(m["bridge_member"] == "REAL_MAPPING" for m in listed)


async def test_import_bridge_mappings_merge_does_not_update_existing(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "ACCOUNT",
            "source_member": "1000",
            "bridge_member": "OLD_VALUE",
        },
    )

    csv_content = (
        "app_number,dimension_name,source_member,bridge_member,flip_sign,bridge_comment\r\n"
        "1,ACCOUNT,1000,NEW_VALUE,false,updated\r\n"
        "1,ACCOUNT,2000,PAYABLE,true,\r\n"
    )
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/import",
        headers=_auth(token),
        files={"file": ("mappings.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    listed = (
        await client.get(f"{RECONS_URL}/{recon_id}/bridge-mappings", headers=_auth(token))
    ).json()
    assert len(listed) == 2
    kept = next(m for m in listed if m["source_member"] == "1000")
    assert kept["bridge_member"] == "OLD_VALUE"
    new_one = next(m for m in listed if m["source_member"] == "2000")
    assert new_one["flip_sign"] is True


async def test_import_overwrite_replaces_that_app_only(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    for source, app in (("1000", 1), ("KEEP", 2)):
        await client.post(
            f"{RECONS_URL}/{recon_id}/bridge-mappings",
            headers=_auth(token),
            json={
                "app_number": app,
                "dimension_name": "ACCOUNT",
                "source_member": source,
                "bridge_member": "OLD",
            },
        )

    csv_content = (
        "dimension,source member,flip sign,bridge member,comments\r\n"
        "ACCOUNT,1000,No,NEW,\r\n"
    )
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/import",
        headers=_auth(token),
        data={"app_number": 1, "overwrite": True},
        files={"file": ("mappings.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 200
    listed = (
        await client.get(
            f"{RECONS_URL}/{recon_id}/bridge-mappings?page_size=50", headers=_auth(token)
        )
    ).json()
    app1 = [m for m in listed if m["app_number"] == 1]
    app2 = [m for m in listed if m["app_number"] == 2]
    assert len(app1) == 1
    assert app1[0]["bridge_member"] == "NEW"
    assert len(app2) == 1
    assert app2[0]["source_member"] == "KEEP"


async def test_non_owner_cannot_manage_bridge_mappings(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    response = await client.get(f"{RECONS_URL}/{recon_id}/bridge-mappings", headers=_auth(token_b))
    assert response.status_code == 404


async def test_export_and_old_csv_comment_column(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    csv_content = (
        "dimension,source member,flip sign,bridge member,comments\r\n"
        "ACCOUNT,1000,Yes,CASH,keep this\r\n"
    )
    imported = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/import",
        headers=_auth(token),
        data={"app_number": 1, "overwrite": True},
        files={"file": ("mappings.csv", csv_content, "text/csv")},
    )
    assert imported.status_code == 200
    body = imported.json()[0]
    assert body["flip_sign"] is True
    assert body["dim_comment"] == "keep this"
    assert body["bridge_comment"] == "keep this"

    exported = await client.get(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/export?app_number=1", headers=_auth(token)
    )
    assert exported.status_code == 200
    text = exported.text
    assert "Dimension,Source Member,Flip Sign,Bridge Member,Comment" in text
    assert "ACCOUNT,1000,YES,CASH,keep this" in text
