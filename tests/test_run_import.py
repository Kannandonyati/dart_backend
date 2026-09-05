"""Run Import integration tests: upload endpoint through to the actual
imported rows, exercising the real validation/parsing/bulk-insert path.

The Celery task itself (`run_import_task`) is not invoked through Celery
here — no worker runs during tests, so `.delay()` only enqueues to
Redis and nothing consumes it (confirmed real: an uploaded run stays
`pending` — see `test_upload_creates_a_pending_run_and_does_not_run_
synchronously`). Every other test calls `_run_import` directly, the
same async function the Celery task wraps, against the same test
database — this exercises the real business logic end-to-end without
needing a live worker process in the test environment."""

import uuid
from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.import_run import ImportRun
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


async def _owner_recon_with_app_and_dimensions(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> tuple[str, str]:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (
        await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})
    ).json()["id"]
    await configure_dimensions(
        client, token, recon_id, [("YEAR", "1"), ("AMOUNT", "2"), ("PERIOD", "3")]
    )
    return token, recon_id


async def test_upload_creates_a_pending_run_and_does_not_run_synchronously(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)
    csv_content = b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n"

    response = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("data.csv", csv_content, "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["file_name"] == "data.csv"
    assert body["row_count"] is None


async def test_upload_to_unconfigured_app_is_404(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """App 3 is not created with the recon, so upload is 404 until Add
    Application has run for that slot."""
    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)
    response = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 3},
        files={"file": ("data.csv", b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n", "text/csv")},
    )
    assert response.status_code == 404


async def test_full_import_run_completes_and_rows_are_readable(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], db_session: AsyncSession
) -> None:
    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)
    csv_content = b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n2025,200,02\r\n"

    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("data.csv", csv_content, "text/csv")},
    )
    run_id = uploaded.json()["id"]

    await _run_import(uuid.UUID(run_id))

    status_response = await client.get(
        f"{RECONS_URL}/{recon_id}/imports/{run_id}", headers=_auth(token)
    )
    assert status_response.status_code == 200
    body = status_response.json()
    assert body["status"] == "completed"
    assert body["row_count"] == 2
    assert body["error_message"] is None

    data_response = await client.get(
        f"{RECONS_URL}/{recon_id}/imports/data?app_number=1", headers=_auth(token)
    )
    assert data_response.status_code == 200
    rows = data_response.json()
    assert len(rows) == 2
    assert rows[0]["data"] == {"YEAR": "2024", "AMOUNT": "100", "PERIOD": "01"}
    assert rows[1]["data"] == {"YEAR": "2025", "AMOUNT": "200", "PERIOD": "02"}
    assert data_response.headers["x-total-count"] == "2"


async def test_export_returns_csv_for_one_app_and_zip_for_all(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)
    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("data.csv", b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n", "text/csv")},
    )
    await _run_import(uuid.UUID(uploaded.json()["id"]))

    csv_export = await client.get(
        f"{RECONS_URL}/{recon_id}/imports/export?app_number=1", headers=_auth(token)
    )
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert b"YEAR" in csv_export.content
    assert b"2024" in csv_export.content

    zip_export = await client.get(f"{RECONS_URL}/{recon_id}/imports/export", headers=_auth(token))
    assert zip_export.status_code == 200
    assert zip_export.headers["content-type"].startswith("application/zip")


async def test_import_run_with_invalid_file_fails_with_error_message(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)
    # AMOUNT blank with no configured default — must be rejected.
    csv_content = b"YEAR,AMOUNT,PERIOD\r\n2024,,01\r\n"

    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("bad.csv", csv_content, "text/csv")},
    )
    run_id = uploaded.json()["id"]

    await _run_import(uuid.UUID(run_id))

    status_response = await client.get(
        f"{RECONS_URL}/{recon_id}/imports/{run_id}", headers=_auth(token)
    )
    body = status_response.json()
    assert body["status"] == "failed"
    assert "Row 2, column 2" in body["error_message"]
    assert body["row_count"] is None

    data_response = await client.get(
        f"{RECONS_URL}/{recon_id}/imports/data?app_number=1", headers=_auth(token)
    )
    assert data_response.json() == []


async def test_import_deletes_the_uploaded_file_after_processing(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], db_session: AsyncSession
) -> None:
    import os

    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)
    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("data.csv", b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n", "text/csv")},
    )
    run_id = uploaded.json()["id"]

    run = (
        await db_session.execute(select(ImportRun).where(ImportRun.id == uuid.UUID(run_id)))
    ).scalar_one()
    stored_path = run.file_path
    assert os.path.exists(stored_path)  # noqa: ASYNC240 — trivial local stat, not I/O worth async-ifying in a test

    await _run_import(uuid.UUID(run_id))

    assert not os.path.exists(stored_path)  # noqa: ASYNC240


async def test_non_owner_cannot_upload_or_list_imports(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")

    listed = await client.get(f"{RECONS_URL}/{recon_id}/imports", headers=_auth(token_b))
    assert listed.status_code == 404

    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token_b),
        data={"app_number": 1},
        files={"file": ("data.csv", b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n", "text/csv")},
    )
    assert uploaded.status_code == 404


async def test_reimport_overwrites_rows_for_that_app_only(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """A second successful upload for an app replaces that app's rows.
    Other apps on the same recon are left alone. History of prior
    ImportRun rows is unchanged — only `imported_rows` is overwritten."""
    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)

    first = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={
            "file": (
                "app1.csv",
                b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n2025,200,02\r\n",
                "text/csv",
            )
        },
    )
    await _run_import(uuid.UUID(first.json()["id"]))

    other = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 2},
        files={
            "file": (
                "app2.csv",
                b"YEAR,AMOUNT,PERIOD\r\n2024,50,01\r\n",
                "text/csv",
            )
        },
    )
    await _run_import(uuid.UUID(other.json()["id"]))

    second = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={
            "file": (
                "app1-again.csv",
                b"YEAR,AMOUNT,PERIOD\r\n2026,1,03\r\n2026,2,04\r\n2026,3,05\r\n",
                "text/csv",
            )
        },
    )
    await _run_import(uuid.UUID(second.json()["id"]))

    app1 = await client.get(
        f"{RECONS_URL}/{recon_id}/imports/data?app_number=1", headers=_auth(token)
    )
    app2 = await client.get(
        f"{RECONS_URL}/{recon_id}/imports/data?app_number=2", headers=_auth(token)
    )
    assert app1.headers["x-total-count"] == "3"
    assert [row["data"]["AMOUNT"] for row in app1.json()] == ["1", "2", "3"]
    assert app2.headers["x-total-count"] == "1"
    assert app2.json()[0]["data"]["AMOUNT"] == "50"

    history = await client.get(f"{RECONS_URL}/{recon_id}/imports", headers=_auth(token))
    assert history.headers["x-total-count"] == "3"


async def test_failed_reimport_keeps_previous_rows(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon_with_app_and_dimensions(client, make_user)
    first = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("ok.csv", b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n", "text/csv")},
    )
    await _run_import(uuid.UUID(first.json()["id"]))

    bad = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("bad.csv", b"YEAR,AMOUNT,PERIOD\r\n2024,,01\r\n", "text/csv")},
    )
    await _run_import(uuid.UUID(bad.json()["id"]))

    data = await client.get(
        f"{RECONS_URL}/{recon_id}/imports/data?app_number=1", headers=_auth(token)
    )
    assert data.headers["x-total-count"] == "1"
    assert data.json()[0]["data"]["AMOUNT"] == "100"

