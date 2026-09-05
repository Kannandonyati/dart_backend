"""Run Report: variance computation (incl. bridge-resolved matching and
flip_sign), sign-off, saved filters, drill-down, export, and access
control."""

import uuid
from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.user import User
from app.tasks.bridge_tasks import _run_bridge
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
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], name: str = "R1"
) -> tuple[str, str]:
    await make_user(
        email=f"{name.lower()}-a@dart.com", username=f"{name.lower()}_a", password="Password123!"
    )
    token = await _login(client, f"{name.lower()}-a@dart.com", "Password123!")
    recon_id = (
        await client.post(RECONS_URL, headers=_auth(token), json={"name": name})
    ).json()["id"]
    return token, recon_id


async def _add_dims_and_apps(client: AsyncClient, token: str, recon_id: str) -> None:
    await configure_dimensions(
        client,
        token,
        recon_id,
        [("YEAR", "1"), ("ACCOUNT", "2"), ("AMOUNT", "3"), ("PERIOD", "4")],
    )


async def _import_csv(
    client: AsyncClient, token: str, recon_id: str, app_number: int, csv_body: bytes
) -> None:
    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": app_number},
        files={"file": ("d.csv", csv_body, "text/csv")},
    )
    await _run_import(uuid.UUID(uploaded.json()["id"]))


async def _bridge_map(
    client: AsyncClient,
    token: str,
    recon_id: str,
    *,
    app_number: int,
    dimension_name: str,
    source_member: str,
    bridge_member: str,
    flip_sign: bool = False,
) -> None:
    resp = await client.post(
        f"{RECONS_URL}/{recon_id}/bridge-mappings",
        headers=_auth(token),
        json={
            "app_number": app_number,
            "dimension_name": dimension_name,
            "source_member": source_member,
            "bridge_member": bridge_member,
            "flip_sign": flip_sign,
        },
    )
    assert resp.status_code == 201, resp.text


async def _matched_recon(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> tuple[str, str]:
    token, recon_id = await _owner_recon(client, make_user, name="ReportRecon")
    await _add_dims_and_apps(client, token, recon_id)
    await _import_csv(
        client,
        token,
        recon_id,
        1,
        b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,ACCT_A,100.00,01\r\n2024,ACCT_B,50.00,01\r\n",
    )
    await _import_csv(
        client,
        token,
        recon_id,
        2,
        b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,ACCT_A_ALT,100.00,01\r\n2024,ACCT_C,30.00,01\r\n",
    )
    await _bridge_map(
        client, token, recon_id, app_number=1, dimension_name="ACCOUNT",
        source_member="ACCT_A", bridge_member="ACCT_A",
    )
    await _bridge_map(
        client, token, recon_id, app_number=2, dimension_name="ACCOUNT",
        source_member="ACCT_A_ALT", bridge_member="ACCT_A",
    )
    return token, recon_id


async def test_run_report_matches_via_bridge_resolved_key(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _matched_recon(client, make_user)
    response = await client.post(f"{RECONS_URL}/{recon_id}/report/run", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_rows"] == 3
    assert body["summary"]["variance_count"] == 2

    rows = {row["match_key"]["ACCOUNT"]: row for row in body["rows"]}
    assert rows["ACCT_A"]["app1_amount"] == "100.00"
    assert rows["ACCT_A"]["app2_amount"] == "100.00"
    assert rows["ACCT_A"]["is_variance"] is False
    assert rows["ACCT_B"]["app2_data"] is None
    assert rows["ACCT_C"]["app1_data"] is None
    assert "AMOUNT" not in rows["ACCT_A"]["match_key"]


async def test_variance_threshold_suppresses_small_differences(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _matched_recon(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/report/run?variance_threshold=50",
        headers=_auth(token),
    )
    body = response.json()
    # ACCT_B has variance exactly 50 (not > 50) and ACCT_C has variance -30
    # (abs 30, not > 50) -- both suppressed at this threshold.
    assert body["summary"]["variance_count"] == 0


async def test_flip_sign_negates_matched_amount(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user, name="FlipRecon")
    await _add_dims_and_apps(client, token, recon_id)
    await _import_csv(
        client, token, recon_id, 1, b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,ACCT_X,40.00,01\r\n"
    )
    await _import_csv(
        client, token, recon_id, 2, b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,ACCT_X_ALT,40.00,01\r\n"
    )
    await _bridge_map(
        client, token, recon_id, app_number=1, dimension_name="ACCOUNT",
        source_member="ACCT_X", bridge_member="ACCT_X",
    )
    await _bridge_map(
        client, token, recon_id, app_number=2, dimension_name="ACCOUNT",
        source_member="ACCT_X_ALT", bridge_member="ACCT_X", flip_sign=True,
    )

    response = await client.post(f"{RECONS_URL}/{recon_id}/report/run", headers=_auth(token))
    row = response.json()["rows"][0]
    assert row["app1_amount"] == "40.00"
    assert row["app2_amount"] == "-40.00"
    assert row["variance"] == "80.00"


async def test_kickout_rows_are_excluded_from_report(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user, name="KickoutRecon")
    await _add_dims_and_apps(client, token, recon_id)
    await _import_csv(
        client, token, recon_id, 1, b"YEAR,ACCOUNT,AMOUNT,PERIOD\r\n2024,UNMAPPED,10.00,01\r\n"
    )
    run = await client.post(f"{RECONS_URL}/{recon_id}/bridge-runs", headers=_auth(token))
    await _run_bridge(uuid.UUID(run.json()["id"]))

    response = await client.post(f"{RECONS_URL}/{recon_id}/report/run", headers=_auth(token))
    assert response.json()["summary"]["total_rows"] == 0


async def test_report_filter_narrows_matching_rows(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _matched_recon(client, make_user)
    created = await client.post(
        f"{RECONS_URL}/{recon_id}/report/filters",
        headers=_auth(token),
        json={"name": "Only A", "criteria": {"ACCOUNT": ["ACCT_A", "ACCT_A_ALT"]}},
    )
    assert created.status_code == 201
    filter_id = created.json()["id"]

    response = await client.post(
        f"{RECONS_URL}/{recon_id}/report/run?filter_id={filter_id}", headers=_auth(token)
    )
    body = response.json()
    assert body["summary"]["total_rows"] == 1
    assert body["rows"][0]["match_key"]["ACCOUNT"] == "ACCT_A"


async def test_duplicate_filter_name_is_conflict(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user, name="FilterDupRecon")
    body = {"name": "Dup", "criteria": {"ACCOUNT": ["X"]}}
    await client.post(f"{RECONS_URL}/{recon_id}/report/filters", headers=_auth(token), json=body)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/report/filters", headers=_auth(token), json=body
    )
    assert response.status_code == 409


async def test_filter_members_lists_distinct_dimension_values(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _matched_recon(client, make_user)
    response = await client.get(
        f"{RECONS_URL}/{recon_id}/report/filters/members?dimension_name=ACCOUNT&app_number=1",
        headers=_auth(token),
    )
    assert response.status_code == 200
    assert sorted(response.json()) == ["ACCT_A", "ACCT_B"]


async def test_drill_down_returns_matching_row_only(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _matched_recon(client, make_user)
    response = await client.get(
        f"{RECONS_URL}/{recon_id}/report/drill-down"
        "?dimension_names=YEAR&dimension_names=ACCOUNT&values=2024&values=ACCT_B",
        headers=_auth(token),
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    assert rows[0]["match_key"]["ACCOUNT"] == "ACCT_B"


async def test_export_returns_csv(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _matched_recon(client, make_user)
    response = await client.get(f"{RECONS_URL}/{recon_id}/report/export", headers=_auth(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "ACCT_B" in response.text


async def test_last_refresh_reports_most_recent_completed_import(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _matched_recon(client, make_user)
    response = await client.get(
        f"{RECONS_URL}/{recon_id}/report/last-refresh", headers=_auth(token)
    )
    assert response.status_code == 200
    by_app = {r["app_number"]: r["last_refresh"] for r in response.json()}
    assert by_app[1] is not None
    assert by_app[2] is not None


async def test_signoff_upserts_per_app(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user, name="SignoffRecon")
    signed = await client.post(
        f"{RECONS_URL}/{recon_id}/report/signoff",
        headers=_auth(token),
        json={"app_numbers": [1, 2], "signed_off": True},
    )
    assert signed.status_code == 200
    for row in signed.json():
        assert row["signed_off"] is True
        assert row["signed_off_by_id"] is not None
        assert row["signed_off_at"] is not None

    unsigned = await client.post(
        f"{RECONS_URL}/{recon_id}/report/signoff",
        headers=_auth(token),
        json={"app_numbers": [1], "signed_off": False},
    )
    assert unsigned.json()[0]["signed_off"] is False

    listed = await client.get(f"{RECONS_URL}/{recon_id}/report/signoff", headers=_auth(token))
    by_app = {r["app_number"]: r["signed_off"] for r in listed.json()}
    assert by_app == {1: False, 2: True}


async def test_non_owner_cannot_run_or_signoff_report(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user, name="PrivateReportRecon")
    await make_user(email="report-b@dart.com", username="report_b", password="Password123!")
    token_b = await _login(client, "report-b@dart.com", "Password123!")

    run_resp = await client.post(f"{RECONS_URL}/{recon_id}/report/run", headers=_auth(token_b))
    assert run_resp.status_code == 404

    signoff_resp = await client.post(
        f"{RECONS_URL}/{recon_id}/report/signoff",
        headers=_auth(token_b),
        json={"app_numbers": [1], "signed_off": True},
    )
    assert signoff_resp.status_code == 404

    filters_resp = await client.get(
        f"{RECONS_URL}/{recon_id}/report/filters", headers=_auth(token_b)
    )
    assert filters_resp.status_code == 404
