"""Audit Log recording/reads and User Maintenance (invite, admin-mediated
password reset, deletion)."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient

from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
RECONS_URL = "/api/v1/recons"
USERS_URL = "/api/v1/users"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _admin(client: AsyncClient, make_user: Callable[..., Awaitable[User]]) -> str:
    await make_user(
        email="admin9@dart.com", username="admin9", password="AdminPass123!", is_superuser=True
    )
    return await _login(client, "admin9@dart.com", "AdminPass123!")


async def _plain_user(client: AsyncClient, make_user: Callable[..., Awaitable[User]]) -> str:
    await make_user(email="plain9@dart.com", username="plain9", password="PlainPass123!")
    return await _login(client, "plain9@dart.com", "PlainPass123!")


async def test_recon_lifecycle_is_audited(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    created = await client.post(
        RECONS_URL, headers=_auth(token), json={"name": "AuditedRecon"}
    )
    recon_id = created.json()["id"]

    await client.patch(
        f"{RECONS_URL}/{recon_id}", headers=_auth(token), json={"description": "updated"}
    )
    await client.delete(f"{RECONS_URL}/{recon_id}", headers=_auth(token))

    logs = await client.get(f"{RECONS_URL}/{recon_id}/audit-logs", headers=_auth(token))
    assert logs.status_code == 200
    actions = [entry["action"] for entry in logs.json()]
    assert actions == ["recon.deleted", "recon.updated", "recon.created"]


async def test_login_is_audited_with_resolved_names(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Old DART's User Logs show every login as an "N/A"-stage row with the
    real username — not just user-management actions. Also confirms the
    join-at-read-time enrichment: `actor_username`/`recon_name` come back
    resolved, not raw UUIDs or "—" (see audit_logs.py's `_to_read`)."""
    await make_user(email="loginaudit@dart.com", username="loginaudit", password="Password123!")
    await _login(client, "loginaudit@dart.com", "Password123!")

    token = await _login(client, "loginaudit@dart.com", "Password123!")
    await client.post(RECONS_URL, headers=_auth(token), json={"name": "LoginAuditRecon"})

    logs = await client.get("/api/v1/audit-logs/mine", headers=_auth(token))
    entries = logs.json()["data"]

    login_entries = [e for e in entries if e["action"] == "auth.login"]
    assert login_entries
    assert login_entries[0]["actor_username"] == "loginaudit"
    assert login_entries[0]["recon_id"] is None

    recon_created = next(e for e in entries if e["action"] == "recon.created")
    assert recon_created["recon_name"] == "LoginAuditRecon"


async def test_report_signoff_is_audited(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    recon_id = (
        await client.post(RECONS_URL, headers=_auth(token), json={"name": "SignoffAuditRecon"})
    ).json()["id"]
    await client.post(
        f"{RECONS_URL}/{recon_id}/report/signoff",
        headers=_auth(token),
        json={"app_numbers": [1], "signed_off": True},
    )
    logs = await client.get(f"{RECONS_URL}/{recon_id}/audit-logs", headers=_auth(token))
    actions = [entry["action"] for entry in logs.json()]
    assert "report.signoff" in actions


async def test_users_audit_log_lists_every_users_actions(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Manage Users' User Logs used to show every user's operational
    trail, not just the signed-in admin's. GET /audit-logs/users is that
    page's feed — privilege-gated (user:manage), paginated."""
    admin_token = await _admin(client, make_user)
    plain_token = await _plain_user(client, make_user)
    await client.post(RECONS_URL, headers=_auth(plain_token), json={"name": "OtherUserRecon"})

    forbidden = await client.get("/api/v1/audit-logs/users", headers=_auth(plain_token))
    assert forbidden.status_code == 403

    allowed = await client.get(
        "/api/v1/audit-logs/users",
        params={"page": 1, "page_size": 50},
        headers=_auth(admin_token),
    )
    assert allowed.status_code == 200
    names = [
        entry["detail"]["name"]
        for entry in allowed.json()["data"]
        if entry.get("detail") and "name" in entry["detail"]
    ]
    assert "OtherUserRecon" in names
    assert allowed.json()["pagination"]["total_count"] >= 1


async def test_global_audit_log_requires_superuser(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    admin_token = await _admin(client, make_user)
    plain_token = await _plain_user(client, make_user)

    forbidden = await client.get("/api/v1/audit-logs", headers=_auth(plain_token))
    assert forbidden.status_code == 403

    allowed = await client.get("/api/v1/audit-logs", headers=_auth(admin_token))
    assert allowed.status_code == 200


async def test_mine_audit_log_scoped_to_caller(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    admin_token = await _admin(client, make_user)
    plain_token = await _plain_user(client, make_user)

    await client.post(RECONS_URL, headers=_auth(admin_token), json={"name": "AdminOwnedRecon"})
    await client.post(RECONS_URL, headers=_auth(plain_token), json={"name": "PlainOwnedRecon"})

    mine = await client.get("/api/v1/audit-logs/mine", headers=_auth(plain_token))
    assert mine.status_code == 200
    names = [
        entry["detail"]["name"]
        for entry in mine.json()["data"]
        if entry.get("detail") and "name" in entry["detail"]
    ]
    assert "PlainOwnedRecon" in names
    assert "AdminOwnedRecon" not in names


async def test_mine_audit_log_returns_real_pagination_totals(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Same pager requirement as GET /users (see test_users.py's sibling
    test) — Manage Users' "User activity" table needs a real total_count."""
    token = await _admin(client, make_user)
    for i in range(3):
        await client.post(RECONS_URL, headers=_auth(token), json={"name": f"PagedAuditRecon{i}"})

    response = await client.get(
        "/api/v1/audit-logs/mine", params={"page": 1, "page_size": 2}, headers=_auth(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    # at least the 3 recon.created events (login may add more)
    assert body["pagination"]["total_count"] >= 3
    assert body["pagination"]["has_more"] is True


async def test_audit_log_export_is_csv(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    await client.post(RECONS_URL, headers=_auth(token), json={"name": "ExportedAuditRecon"})
    response = await client.get("/api/v1/audit-logs/export", headers=_auth(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "recon.created" in response.text


async def test_invite_accept_and_login_flow(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    invited = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(token),
        json={"email": "invitee@dart.com", "username": "invitee"},
    )
    assert invited.status_code == 201
    invite_token = invited.json()["invite_token"]

    login_before = await client.post(
        LOGIN_URL, json={"email": "invitee@dart.com", "password": "anything"}
    )
    assert login_before.status_code == 401

    accepted = await client.post(
        f"{USERS_URL}/accept-invite",
        json={"invite_token": invite_token, "password": "InviteeRealPass123!"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["is_active"] is True

    login_after = await client.post(
        LOGIN_URL, json={"email": "invitee@dart.com", "password": "InviteeRealPass123!"}
    )
    assert login_after.status_code == 200


async def test_duplicate_invite_is_conflict(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    body = {"email": "dup-invite@dart.com", "username": "dupinvite"}
    await client.post(f"{USERS_URL}/invite", headers=_auth(token), json=body)
    second = await client.post(f"{USERS_URL}/invite", headers=_auth(token), json=body)
    assert second.status_code == 409


async def test_invite_requires_privilege(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    plain_token = await _plain_user(client, make_user)
    response = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(plain_token),
        json={"email": "blocked@dart.com", "username": "blocked"},
    )
    assert response.status_code == 403


async def test_invalid_invite_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        f"{USERS_URL}/accept-invite",
        json={"invite_token": "not-a-real-token", "password": "SomePassword123!"},
    )
    assert response.status_code == 401


async def test_list_invited_users_excludes_active_users(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(token),
        json={"email": "pending@dart.com", "username": "pending"},
    )
    listed = await client.get(f"{USERS_URL}/invited", headers=_auth(token))
    assert listed.status_code == 200
    emails = [u["email"] for u in listed.json()["data"]]
    assert "pending@dart.com" in emails
    assert "admin9@dart.com" not in emails


async def test_list_invited_users_returns_real_pagination_totals(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Same pager requirement as GET /users (see test_users.py's sibling
    test) — Invited Users' "Page X of Y - N total" needs a real
    total_count, not len(current page)."""
    token = await _admin(client, make_user)
    for i in range(3):
        await client.post(
            f"{USERS_URL}/invite",
            headers=_auth(token),
            json={"email": f"pending{i}@dart.com", "username": f"pending{i}"},
        )

    response = await client.get(
        f"{USERS_URL}/invited", params={"page": 1, "page_size": 2}, headers=_auth(token)
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) == 2
    assert body["pagination"]["total_count"] == 3
    assert body["pagination"]["has_more"] is True


async def test_deleted_user_disappears_from_both_lists(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Regression test: `is_active=False` means two different things
    (never redeemed an invite vs. was deleted) — `GET /users/invited`
    must only report the former. A deleted user also must not linger in
    `GET /users` with some "deactivated" status — the reference system's
    Manage Users screen has no such state; deleting removes the row
    outright (see User.deleted_at's docstring)."""
    admin_token = await _admin(client, make_user)
    target = await make_user(
        email="was-active@dart.com", username="wasactive", password="Password123!"
    )

    await client.delete(f"{USERS_URL}/{target.id}", headers=_auth(admin_token))

    listed = await client.get(f"{USERS_URL}/invited", headers=_auth(admin_token))
    emails = [u["email"] for u in listed.json()["data"]]
    assert "was-active@dart.com" not in emails

    registered = await client.get(USERS_URL, headers=_auth(admin_token))
    registered_emails = [u["email"] for u in registered.json()["data"]]
    assert "was-active@dart.com" not in registered_emails


async def test_invite_without_username_derives_from_email(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """The reference frontend's invite form only ever collects an email —
    confirms the backend can carry that alone, matching the old backend's
    own `username = email.split('@')[0]` convention."""
    token = await _admin(client, make_user)
    invited = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(token),
        json={"email": "no-username@dart.com"},
    )
    assert invited.status_code == 201
    assert invited.json()["username"] == "no-username"


async def test_resend_invite_reuses_same_pending_account(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    first = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(token),
        json={"email": "resend-me@dart.com", "username": "resendme"},
    )
    first_user_id = first.json()["user_id"]
    first_token = first.json()["invite_token"]

    resent = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(token),
        json={"email": "resend-me@dart.com", "resend": True},
    )
    assert resent.status_code == 201
    assert resent.json()["user_id"] == first_user_id
    assert resent.json()["invite_token"] != first_token

    # The resent (fresh) token still works to accept the invite.
    accepted = await client.post(
        f"{USERS_URL}/accept-invite",
        json={"invite_token": resent.json()["invite_token"], "password": "ResendPass123!"},
    )
    assert accepted.status_code == 200


async def test_resend_invite_fails_for_unknown_email(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    response = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(token),
        json={"email": "never-invited@dart.com", "resend": True},
    )
    assert response.status_code == 404


async def test_resend_invite_fails_once_already_accepted(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    token = await _admin(client, make_user)
    invited = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(token),
        json={"email": "already-accepted@dart.com", "username": "alreadyaccepted"},
    )
    await client.post(
        f"{USERS_URL}/accept-invite",
        json={
            "invite_token": invited.json()["invite_token"],
            "password": "AcceptedPass123!",
        },
    )

    response = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(token),
        json={"email": "already-accepted@dart.com", "resend": True},
    )
    assert response.status_code == 409


async def test_admin_mediated_password_reset_flow(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    admin_token = await _admin(client, make_user)
    target = await make_user(
        email="resettarget@dart.com", username="resettarget", password="OldPassword123!"
    )

    generated = await client.post(
        f"{USERS_URL}/{target.id}/reset-token", headers=_auth(admin_token)
    )
    assert generated.status_code == 200
    reset_token = generated.json()["reset_token"]

    submitted = await client.post(
        f"{USERS_URL}/reset-password",
        json={"reset_token": reset_token, "new_password": "BrandNewPassword123!"},
    )
    assert submitted.status_code == 200

    old_login = await client.post(
        LOGIN_URL, json={"email": "resettarget@dart.com", "password": "OldPassword123!"}
    )
    assert old_login.status_code == 401

    new_login = await client.post(
        LOGIN_URL, json={"email": "resettarget@dart.com", "password": "BrandNewPassword123!"}
    )
    assert new_login.status_code == 200


async def test_delete_user_blocks_login_and_repeat_delete_is_404(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    admin_token = await _admin(client, make_user)
    target = await make_user(
        email="delete-me@dart.com", username="deleteme", password="Password123!"
    )

    deleted = await client.delete(f"{USERS_URL}/{target.id}", headers=_auth(admin_token))
    assert deleted.status_code == 204

    login = await client.post(
        LOGIN_URL, json={"email": "delete-me@dart.com", "password": "Password123!"}
    )
    assert login.status_code == 401

    # Deleting an already-deleted user (or fetching them directly) 404s,
    # same "gone, not just hidden" behavior as the list endpoints.
    redeleted = await client.delete(f"{USERS_URL}/{target.id}", headers=_auth(admin_token))
    assert redeleted.status_code == 404
    fetched = await client.get(f"{USERS_URL}/{target.id}", headers=_auth(admin_token))
    assert fetched.status_code == 404
