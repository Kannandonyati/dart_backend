"""Maintenance system logs — old Dart userlog / techlog / dblog contract."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.system_log import record_system_log
from app.models.system_log import SystemLog
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
SYSTEM_LOGS_URL = "/api/v1/system-logs"
USERS_ME_URL = "/api/v1/users/me"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    assert response.status_code == 200
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_login_writes_userlog_with_real_columns(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="slog@dart.com", username="slog", password="SlogPass123!", is_superuser=True
    )
    token = await _login(client, "slog@dart.com", "SlogPass123!")

    listed = await client.get(SYSTEM_LOGS_URL, headers=_auth(token))
    assert listed.status_code == 200
    rows = listed.json()["data"]
    userlogs = [row for row in rows if row["log_name"] == "userlog"]
    assert userlogs
    login_row = next(row for row in userlogs if "authenticated" in row["log_message"].lower())
    assert login_row["logging_level"] == "INFO"
    assert login_row["username"] == "slog"
    assert login_row["user_email"] == "slog@dart.com"
    assert login_row["request_url"] == "/api/v1/auth/login"
    assert login_row["request_id"]


async def test_authenticated_request_writes_userlog(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="mw@dart.com", username="mwuser", password="MwPass123!", is_superuser=True
    )
    token = await _login(client, "mw@dart.com", "MwPass123!")
    await client.get(USERS_ME_URL, headers=_auth(token))

    listed = await client.get(
        SYSTEM_LOGS_URL, params={"log_name": "userlog"}, headers=_auth(token)
    )
    messages = [row["log_message"] for row in listed.json()["data"]]
    assert any("GET /api/v1/users/me" in message for message in messages)


async def test_techlog_and_dblog_round_trip(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    db_session: AsyncSession,
) -> None:
    admin = await make_user(
        email="levels@dart.com", username="levels", password="LevelPass123!", is_superuser=True
    )
    await record_system_log(
        log_name="techlog",
        logging_level="ERROR",
        log_message="unhandled boom",
        request_url="/api/v1/recons",
        request_id="req-tech",
        username="levels",
        user_email="levels@dart.com",
        actor_user_id=admin.id,
        event_stage="recons",
    )
    await record_system_log(
        log_name="dblog",
        logging_level="ERROR",
        log_message="relation missing",
        request_url="/api/v1/imports",
        request_id="req-db",
        username="levels",
        event_stage="import",
        variable_state={"function": "import_file"},
    )

    token = await _login(client, "levels@dart.com", "LevelPass123!")
    listed = await client.get(SYSTEM_LOGS_URL, headers=_auth(token))
    names = {row["log_name"] for row in listed.json()["data"]}
    assert {"userlog", "techlog", "dblog"} <= names

    tech = next(row for row in listed.json()["data"] if row["log_name"] == "techlog")
    assert tech["logging_level"] == "ERROR"
    assert tech["log_message"] == "unhandled boom"

    stored = (
        await db_session.execute(select(SystemLog).where(SystemLog.log_name == "dblog"))
    ).scalar_one()
    assert stored.variable_state == {"function": "import_file"}


async def test_system_logs_allow_department_admin_not_recon_user(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    db_session: AsyncSession,
) -> None:
    dept = await make_user(
        email="dept@dart.com", username="deptadmin", password="DeptPass123!"
    )
    dept.user_types = ["Department Admin"]
    await db_session.commit()

    recon = await make_user(
        email="recononly@dart.com", username="recononly", password="ReconPass123!"
    )
    recon.user_types = ["Recon User"]
    await db_session.commit()

    dept_token = await _login(client, "dept@dart.com", "DeptPass123!")
    recon_token = await _login(client, "recononly@dart.com", "ReconPass123!")

    allowed = await client.get(SYSTEM_LOGS_URL, headers=_auth(dept_token))
    assert allowed.status_code == 200

    forbidden = await client.get(SYSTEM_LOGS_URL, headers=_auth(recon_token))
    assert forbidden.status_code == 403


async def test_system_logs_export_csv_and_severity_filter(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
) -> None:
    await make_user(
        email="exp@dart.com", username="exp", password="ExpPass123!", is_superuser=True
    )
    await record_system_log(
        log_name="techlog",
        logging_level="ERROR",
        log_message="export me",
        request_id="req-export",
    )
    token = await _login(client, "exp@dart.com", "ExpPass123!")

    full = await client.get(f"{SYSTEM_LOGS_URL}/export", headers=_auth(token))
    assert full.status_code == 200
    assert "text/csv" in full.headers["content-type"]
    assert "log_name" in full.text
    assert "logging_level" in full.text
    assert "export me" in full.text

    filtered = await client.get(
        f"{SYSTEM_LOGS_URL}/export",
        params={"logging_level": "ERROR"},
        headers=_auth(token),
    )
    assert "export me" in filtered.text
    assert "authenticated" not in filtered.text.lower()
