"""Kickouts are unmapped source members, not whole imported rows.

Old DART (`kickout_list.py`) did not treat "imported, but no mappings yet"
as kickouts. Kickouts came from the bridged view after mappings existed
(template upload / Default) or from mapping rows stored as the `kickout`
sentinel. Listing every imported member as a kickout before any template
was a new-app bug.
"""

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


async def _recon_with_unmapped_account(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> tuple[str, str]:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})).json()[
        "id"
    ]
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
    import uuid as uuid_module

    await _run_import(uuid_module.UUID(uploaded.json()["id"]))
    return token, recon_id


async def _map(
    client: AsyncClient,
    token: str,
    recon_id: str,
    *,
    dimension_name: str,
    source_member: str,
    bridge_member: str,
) -> None:
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": dimension_name,
            "source_member": source_member,
            "bridge_member": bridge_member,
        },
    )
    assert response.status_code == 201, response.text


async def test_kickouts_empty_before_any_mappings(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _recon_with_unmapped_account(client, make_user)
    response = await client.get(
        f"{RECONS_URL}/{recon_id}/bridge-kickouts?page_size=50", headers=_auth(token)
    )
    assert response.status_code == 200
    assert response.json() == []
    assert response.headers.get("x-total-count") == "0"


async def test_kickouts_are_unmapped_source_members(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _recon_with_unmapped_account(client, make_user)
    await _map(
        client,
        token,
        recon_id,
        dimension_name="YEAR",
        source_member="2024",
        bridge_member="2024",
    )
    response = await client.get(
        f"{RECONS_URL}/{recon_id}/bridge-kickouts?page_size=50", headers=_auth(token)
    )
    assert response.status_code == 200
    body = response.json()
    dims = {row["dimension_name"] for row in body}
    assert "ACCOUNT" in dims
    assert "PERIOD" in dims
    assert "YEAR" not in dims
    account = next(row for row in body if row["dimension_name"] == "ACCOUNT")
    assert account["source_member"] == "1000"
    assert account["Source_member"] == "1000"
    assert account["Common_dimension_name"] == "ACCOUNT"
    assert account["app_type"] == "App1"
    assert account["Bridge_member"] == ""


async def test_resolve_and_default_kickouts(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _recon_with_unmapped_account(client, make_user)
    await _map(
        client,
        token,
        recon_id,
        dimension_name="YEAR",
        source_member="2024",
        bridge_member="2024",
    )
    resolved = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-kickouts",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "ACCOUNT",
            "source_member": "1000",
            "bridge_member": "CASH",
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["bridge_member"] == "CASH"

    remaining = (
        await client.get(
            f"{RECONS_URL}/{recon_id}/bridge-kickouts?page_size=50", headers=_auth(token)
        )
    ).json()
    assert not any(row["dimension_name"] == "ACCOUNT" for row in remaining)

    defaulted = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-kickouts/default", headers=_auth(token)
    )
    assert defaulted.status_code == 200
    after = (
        await client.get(
            f"{RECONS_URL}/{recon_id}/bridge-kickouts?page_size=50", headers=_auth(token)
        )
    ).json()
    assert after == []
    mappings = (
        await client.get(
            f"{RECONS_URL}/{recon_id}/bridge-mappings?page_size=50", headers=_auth(token)
        )
    ).json()
    period = next(m for m in mappings if m["dimension_name"] == "PERIOD")
    assert period["bridge_member"] == period["source_member"] == "01"


async def test_template_file_dimension_names_resolve_to_common_dims(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old DART joins mappings on the source-file column (COSTCENTRE/GEO)
    via dim_id, then reports kickouts under the common name (PRACTICE).
    New imported rows are keyed by common name, so a template that uses
    file column names must still match — otherwise App 2 shows false
    kickouts for members that the template already mapped.
    """
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})).json()[
        "id"
    ]
    await configure_dimensions(
        client,
        token,
        recon_id,
        [("YEAR", "1"), ("PRACTICE", "2"), ("AMOUNT", "3"), ("PERIOD", "4")],
    )
    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 2},
        files={
            "file": (
                "app2.csv",
                b"YEAR,COSTCENTRE,AMOUNT,PERIOD\r\n"
                b"2024,CPM-Quanta,50,01\r\n"
                b"2024,ERP-Fiserv,10,01\r\n",
                "text/csv",
            )
        },
    )
    import uuid as uuid_module

    await _run_import(uuid_module.UUID(uploaded.json()["id"]))

    csv_content = (
        "dimension, source member, flip sign, bridge member,comments\r\n"
        "YEAR,2024,NO,2024,\r\n"
        "PERIOD,01,NO,01,\r\n"
        "COSTCENTRE,CPM-Quanta,NO,CPM-Quanta,\r\n"
        "PLACEHOLDER,plchldr,NO,plchldr,\r\n"
    )
    imported = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/import",
        headers=_auth(token),
        data={"app_number": 2, "overwrite": True},
        files={"file": ("Bridge_App2.csv", csv_content, "text/csv")},
    )
    assert imported.status_code == 200, imported.text

    kickouts = (
        await client.get(
            f"{RECONS_URL}/{recon_id}/bridge-kickouts?page_size=50&app_number=2",
            headers=_auth(token),
        )
    ).json()
    keys = {(row["dimension_name"], row["source_member"]) for row in kickouts}
    assert ("PRACTICE", "ERP-Fiserv") in keys
    assert ("PRACTICE", "CPM-Quanta") not in keys
    assert keys == {("PRACTICE", "ERP-Fiserv")}
