"""Bridge Run integration tests — the actual kickout-flagging
computation, exercised the same way Phase 5's Run Import task is: call
`_run_bridge` (the async function the Celery task wraps) directly
against the test database, no live worker needed. WebSocket ownership
scoping (`app/ws/router.py`'s `_check_channel_access`) is tested
directly too, for the same reason — no live socket needed to exercise
the actual authorization logic."""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from fastapi import WebSocketException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.tasks.bridge_tasks import _run_bridge
from app.tasks.import_tasks import _run_import
from app.ws.router import _check_channel_access
from tests.recon_setup import configure_dimensions

LOGIN_URL = "/api/v1/auth/login"
RECONS_URL = "/api/v1/recons"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _recon_with_imported_data(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> tuple[str, str, uuid.UUID]:
    """Two apps, YEAR/ACCOUNT/AMOUNT dimensions, one imported row per app:
    app 1 has account 1000, app 2 has account 2000 — plus a bridge
    mapping only for app 1's value, so app 2's row should kick out."""
    user = await make_user(email="a@dart.com", username="a", password="Password123!")
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

    run1 = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={
            "file": ("a.csv", b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,1000,100,01\r\n", "text/csv")
        },
    )
    run2 = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 2},
        files={
            "file": ("b.csv", b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,2000,100,01\r\n", "text/csv")
        },
    )
    await _run_import(uuid.UUID(run1.json()["id"]))
    await _run_import(uuid.UUID(run2.json()["id"]))

    await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "ACCOUNT",
            "source_member": "1000",
            "bridge_member": "CASH",
        },
    )
    await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 1,
            "dimension_name": "YEAR",
            "source_member": "2024",
            "bridge_member": "2024",
        },
    )
    await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": 2,
            "dimension_name": "YEAR",
            "source_member": "2024",
            "bridge_member": "2024",
        },
    )
    for app_number in (1, 2):
        await client.post(
            f"{RECONS_URL}/{recon_id}/bridge-mappings",
            headers=_auth(token),
            json={
                "app_number": app_number,
                "dimension_name": "PERIOD",
                "source_member": "01",
                "bridge_member": "01",
            },
        )
    # ACCOUNT is the only dimension left unmapped, and only for app 2's
    # value 2000 — so exactly that one row should kick out.

    return token, recon_id, user.id


async def test_bridge_run_flags_unmapped_rows_as_kickout(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id, _user_id = await _recon_with_imported_data(client, make_user)

    started = await client.post(f"{RECONS_URL}/{recon_id}/bridge-runs", headers=_auth(token))
    assert started.status_code == 201
    run_id = started.json()["id"]

    await _run_bridge(uuid.UUID(run_id))

    status_response = await client.get(
        f"{RECONS_URL}/{recon_id}/bridge-runs/{run_id}", headers=_auth(token)
    )
    body = status_response.json()
    assert body["status"] == "completed"
    assert body["total_rows"] == 2
    assert body["kickout_count"] == 1

    data = (await client.get(f"{RECONS_URL}/{recon_id}/bridge-data", headers=_auth(token))).json()
    app1_row = next(r for r in data if r["app_number"] == 1)
    app2_row = next(r for r in data if r["app_number"] == 2)
    assert app1_row["kickout"] is False
    assert app1_row["resolved"]["ACCOUNT"] == "CASH"
    assert app1_row["amount"] == "100.00"
    assert app1_row["sign_reversed_amount"] == "100.00"
    assert app1_row["app_type"] == "App1"
    assert app2_row["kickout"] is True
    assert app2_row["resolved"]["ACCOUNT"] == "kickout"


async def test_flip_sign_product_reverses_amount(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id, _user_id = await _recon_with_imported_data(client, make_user)
    listed = (
        await client.get(
            f"{RECONS_URL}/{recon_id}/bridge-mappings?page_size=50", headers=_auth(token)
        )
    ).json()
    account = next(
        m for m in listed if m["app_number"] == 1 and m["dimension_name"] == "ACCOUNT"
    )
    await client.patch(
        f"{RECONS_URL}/{recon_id}/bridge-mappings/{account['id']}",
        headers=_auth(token),
        json={"flip_sign": True},
    )
    data = (await client.get(f"{RECONS_URL}/{recon_id}/bridge-data", headers=_auth(token))).json()
    app1_row = next(r for r in data if r["app_number"] == 1)
    assert app1_row["amount"] == "100.00"
    assert app1_row["sign_reversed_amount"] == "-100.00"


async def test_bridge_data_can_filter_by_kickout(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id, _user_id = await _recon_with_imported_data(client, make_user)
    run_id = (
        await client.post(f"{RECONS_URL}/{recon_id}/bridge-runs", headers=_auth(token))
    ).json()["id"]
    await _run_bridge(uuid.UUID(run_id))

    kickouts = (
        await client.get(f"{RECONS_URL}/{recon_id}/bridge-data?kickout=true", headers=_auth(token))
    ).json()
    assert len(kickouts) == 1
    assert kickouts[0]["app_number"] == 2


async def test_non_owner_cannot_start_or_read_bridge_runs(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id, _user_id = await _recon_with_imported_data(client, make_user)
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    response = await client.post(f"{RECONS_URL}/{recon_id}/bridge-runs", headers=_auth(token_b))
    assert response.status_code == 404


async def test_ws_channel_access_allows_owner_and_denies_stranger(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], db_session: AsyncSession
) -> None:
    token, recon_id, owner_id = await _recon_with_imported_data(client, make_user)
    stranger = await make_user(email="c@dart.com", username="c", password="Password123!")

    started = await client.post(f"{RECONS_URL}/{recon_id}/bridge-runs", headers=_auth(token))
    run_id = started.json()["id"]

    # Owner: no exception.
    await _check_channel_access(f"bridge_run:{run_id}", owner_id)

    # Stranger: denied.
    with pytest.raises(WebSocketException):
        await _check_channel_access(f"bridge_run:{run_id}", stranger.id)

    # Non-job channel: never checked, no exception for anyone.
    await _check_channel_access("some-other-channel", stranger.id)

    # Nonexistent run id: denied, not a 500.
    with pytest.raises(WebSocketException):
        await _check_channel_access(f"bridge_run:{uuid.uuid4()}", owner_id)
