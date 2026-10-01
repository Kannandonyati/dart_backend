"""Workflow Scheduler API — CRUD, access 404s, pause, and in-process runs."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.bridge import BridgeRun, BridgeRunStatus
from app.models.user import User
from app.models.workflow import Workflow, WorkflowRunStatus
from app.services.workflow_runner import run_workflow
from app.tasks.workflow_tasks import enqueue_due_workflows

LOGIN_URL = "/api/v1/auth/login"
RECONS_URL = "/api/v1/recons"
WORKFLOWS_URL = "/api/v1/workflows"
RUNS_URL = "/api/v1/workflow-runs"


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


async def test_create_workflow_defaults_to_recon_pipeline(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    response = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={"name": "Nightly", "recon_id": recon_id, "schedule_cron": "0 2 * * *"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Nightly"
    assert body["recon_name"] == "R1"
    assert body["is_paused"] is False
    assert [s["type"] for s in body["definition"]["steps"]] == [
        "import_app_data",
        "import_app_data",
        "run_bridge",
        "check_kickouts",
        "run_transformation",
        "run_report",
    ]
    assert [s["app_number"] for s in body["definition"]["steps"][:2]] == [1, 2]
    assert body["next_run_at"] is not None


async def test_create_workflow_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        WORKFLOWS_URL,
        json={"name": "X", "recon_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 401


async def test_duplicate_workflow_name_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    payload = {"name": "Dup", "recon_id": recon_id}
    assert (await client.post(WORKFLOWS_URL, headers=_auth(token), json=payload)).status_code == 201
    response = await client.post(WORKFLOWS_URL, headers=_auth(token), json=payload)
    assert response.status_code == 409


async def test_workflow_for_someone_elses_recon_is_404(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token_a, recon_id = await _owner_recon(client, make_user)
    await make_user(email="b@dart.com", username="b", password="Password123!")
    token_b = await _login(client, "b@dart.com", "Password123!")
    created = await client.post(
        WORKFLOWS_URL, headers=_auth(token_a), json={"name": "A's", "recon_id": recon_id}
    )
    workflow_id = created.json()["id"]
    listed = await client.get(WORKFLOWS_URL, headers=_auth(token_b))
    assert listed.json() == []
    got = await client.get(f"{WORKFLOWS_URL}/{workflow_id}", headers=_auth(token_b))
    assert got.status_code == 404


async def test_pause_clears_next_run(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={"name": "P", "recon_id": recon_id, "schedule_cron": "0 * * * *"},
    )
    workflow_id = created.json()["id"]
    paused = await client.patch(
        f"{WORKFLOWS_URL}/{workflow_id}", headers=_auth(token), json={"is_paused": True}
    )
    assert paused.status_code == 200
    assert paused.json()["is_paused"] is True
    assert paused.json()["next_run_at"] is None


async def test_unknown_step_type_is_rejected(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    response = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={
            "name": "Bad",
            "recon_id": recon_id,
            "definition": {"steps": [{"key": "x", "type": "drop_database"}]},
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_step_type"


async def test_default_pipeline_fails_without_app_files(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        WORKFLOWS_URL, headers=_auth(token), json={"name": "Go", "recon_id": recon_id}
    )
    workflow_id = created.json()["id"]
    queued = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    assert queued.status_code == 201, queued.text
    assert queued.json()["status"] == "queued"
    await run_workflow(UUID(queued.json()["id"]))
    done = await client.get(f"{RUNS_URL}/{queued.json()['id']}", headers=_auth(token))
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "failed"
    assert "imported" in (body["error_message"] or "").lower()
    assert body["steps"][0]["step_type"] == "import_app_data"
    assert body["steps"][0]["status"] == "failed"


async def test_second_in_flight_run_is_conflict(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        WORKFLOWS_URL, headers=_auth(token), json={"name": "Once", "recon_id": recon_id}
    )
    workflow_id = created.json()["id"]
    first = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    assert first.status_code == 201
    second = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    assert second.status_code == 409


async def test_kickouts_fail_the_run(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    db_session: AsyncSession,
) -> None:
    user = await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (
        await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})
    ).json()["id"]
    db_session.add(
        BridgeRun(
            recon_id=UUID(recon_id),
            status=BridgeRunStatus.COMPLETED,
            kickout_count=2,
            created_by_id=user.id,
            completed_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={
            "name": "Gate",
            "recon_id": recon_id,
            "definition": {"steps": [{"key": "check_kickouts", "type": "check_kickouts"}]},
        },
    )
    workflow_id = created.json()["id"]
    queued = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    await run_workflow(UUID(queued.json()["id"]))
    done = await client.get(f"{RUNS_URL}/{queued.json()['id']}", headers=_auth(token))
    assert done.json()["status"] == "failed"
    assert done.json()["error_message"] == "Workflow stopped: 2 kickout(s) remain."


async def test_kickouts_can_be_ignored(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    db_session: AsyncSession,
) -> None:
    user = await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (
        await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})
    ).json()["id"]
    db_session.add(
        BridgeRun(
            recon_id=UUID(recon_id),
            status=BridgeRunStatus.COMPLETED,
            kickout_count=2,
            created_by_id=user.id,
            completed_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={
            "name": "Ignore",
            "recon_id": recon_id,
            "definition": {
                "steps": [
                    {
                        "key": "check_kickouts",
                        "type": "check_kickouts",
                        "ignore_kickout": True,
                    }
                ]
            },
        },
    )
    workflow_id = created.json()["id"]
    queued = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    await run_workflow(UUID(queued.json()["id"]))
    done = await client.get(f"{RUNS_URL}/{queued.json()['id']}", headers=_auth(token))
    assert done.json()["status"] == "succeeded"


async def test_kickout_tolerance_allows_small_counts(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    db_session: AsyncSession,
) -> None:
    user = await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    recon_id = (
        await client.post(RECONS_URL, headers=_auth(token), json={"name": "R1"})
    ).json()["id"]
    db_session.add(
        BridgeRun(
            recon_id=UUID(recon_id),
            status=BridgeRunStatus.COMPLETED,
            kickout_count=2,
            created_by_id=user.id,
            completed_at=datetime.now(UTC),
        )
    )
    await db_session.commit()
    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={
            "name": "Tolerate",
            "recon_id": recon_id,
            "definition": {
                "steps": [
                    {
                        "key": "check_kickouts",
                        "type": "check_kickouts",
                        "kickout_tolerance": 2,
                    }
                ]
            },
        },
    )
    workflow_id = created.json()["id"]
    queued = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    await run_workflow(UUID(queued.json()["id"]))
    done = await client.get(f"{RUNS_URL}/{queued.json()['id']}", headers=_auth(token))
    assert done.json()["status"] == "succeeded"


async def test_patch_clears_schedule_and_delete_hides_workflow(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={"name": "ClearMe", "recon_id": recon_id, "schedule_cron": "0 2 * * *"},
    )
    workflow_id = created.json()["id"]
    cleared = await client.patch(
        f"{WORKFLOWS_URL}/{workflow_id}",
        headers=_auth(token),
        json={"schedule_cron": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["schedule_cron"] is None
    assert cleared.json()["next_run_at"] is None
    deleted = await client.delete(f"{WORKFLOWS_URL}/{workflow_id}", headers=_auth(token))
    assert deleted.status_code == 204
    listed = await client.get(WORKFLOWS_URL, headers=_auth(token))
    assert listed.json() == []


async def test_import_app_data_step_fails_without_files(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={
            "name": "Import first",
            "recon_id": recon_id,
            "definition": {
                "steps": [{"key": "import_app_data", "type": "import_app_data"}]
            },
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["latest_run"] is None
    workflow_id = created.json()["id"]
    queued = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    await run_workflow(UUID(queued.json()["id"]))
    done = await client.get(f"{RUNS_URL}/{queued.json()['id']}", headers=_auth(token))
    assert done.json()["status"] == "failed"
    assert "imported" in done.json()["error_message"].lower()
    listed = await client.get(
        WORKFLOWS_URL, headers=_auth(token), params={"page_size": 100}
    )
    row = next(item for item in listed.json() if item["id"] == workflow_id)
    assert row["latest_run"]["status"] == "failed"
    assert row["latest_run"]["current_step"] == "import_app_data"
    recon = await client.get(f"{RECONS_URL}/{recon_id}", headers=_auth(token))
    assert recon.json()["last_modified"] > created.json()["created_at"]


async def test_uploaded_app1_file_is_used_then_app2_is_required(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={"name": "After upload", "recon_id": recon_id},
    )
    workflow_id = created.json()["id"]
    first = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    await run_workflow(UUID(first.json()["id"]))
    failed = await client.get(f"{RUNS_URL}/{first.json()['id']}", headers=_auth(token))
    assert failed.json()["current_step"] == "import_app_data_1"

    uploaded = await client.post(
        f"{RECONS_URL}/{recon_id}/imports",
        headers=_auth(token),
        data={"app_number": 1},
        files={"file": ("app1.csv", b"YEAR,AMOUNT,PERIOD\r\n2024,100,01\r\n", "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text

    second = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    await run_workflow(UUID(second.json()["id"]))
    done = await client.get(f"{RUNS_URL}/{second.json()['id']}", headers=_auth(token))
    body = done.json()
    assert body["status"] == "failed"
    assert body["current_step"] == "import_app_data_2"
    by_key = {step["step_key"]: step for step in body["steps"]}
    assert by_key["import_app_data_1"]["status"] == "succeeded"
    assert by_key["import_app_data_2"]["status"] == "failed"
    assert "app 2" in (body["error_message"] or "").lower()

    third = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    await run_workflow(UUID(third.json()["id"]))
    history = await client.get(f"{RECONS_URL}/{recon_id}/imports", headers=_auth(token))
    app1 = [row for row in history.json() if row["app_number"] == 1]
    assert len(app1) >= 2
    assert app1[0]["status"] == "completed"
    assert app1[0]["completed_at"] >= third.json()["created_at"]
    recon = await client.get(f"{RECONS_URL}/{recon_id}", headers=_auth(token))
    assert recon.json()["last_modified"] >= app1[0]["completed_at"]
    refresh = await client.get(
        f"{RECONS_URL}/{recon_id}/report/last-refresh", headers=_auth(token)
    )
    app1_refresh = next(row for row in refresh.json() if row["app_number"] == 1)
    assert app1_refresh["last_refresh"] >= third.json()["created_at"]


async def test_once_schedule_stays_visible_after_run(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    cron = f"@once {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:00')}"
    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={
            "name": "Once keep",
            "recon_id": recon_id,
            "schedule_cron": cron,
            "timezone": "UTC",
        },
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    queued = await client.post(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    await run_workflow(UUID(queued.json()["id"]))
    got = await client.get(f"{WORKFLOWS_URL}/{workflow_id}", headers=_auth(token))
    assert got.json()["schedule_cron"] == cron
    assert got.json()["next_run_at"] is None


async def test_due_tick_queues_unpaused_workflow(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    db_session: AsyncSession,
) -> None:
    token, recon_id = await _owner_recon(client, make_user)
    created = await client.post(
        WORKFLOWS_URL,
        headers=_auth(token),
        json={"name": "Due", "recon_id": recon_id, "schedule_cron": "0 * * * *"},
    )
    workflow_id = created.json()["id"]
    workflow = (
        await db_session.execute(select(Workflow).where(Workflow.id == workflow_id))
    ).scalar_one()
    workflow.next_run_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    queued = await enqueue_due_workflows()
    assert queued == 1
    history = await client.get(f"{WORKFLOWS_URL}/{workflow_id}/runs", headers=_auth(token))
    assert history.status_code == 200
    assert history.json()[0]["trigger_kind"] == "schedule"
    assert history.json()[0]["status"] == WorkflowRunStatus.QUEUED
