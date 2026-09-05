"""Manage Security leftovers vs old Dart: SSO, audit mode, group GVs."""

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.core.oidc import OidcIdentity
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
SSO_PUBLIC = "/api/v1/sso/providers"
SSO_MANAGE = "/api/v1/sso/providers/manage"
SSO_EXCHANGE = "/api/v1/sso/exchange"
SSO_AUDIT = "/api/v1/sso/audit-logs"
AUDIT_MODE = "/api/v1/audit-mode"
GROUPS = "/api/v1/groups"
GVS = "/api/v1/global-variables"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _provider_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "provider_key": "google",
        "display_name": "Google Workspace",
        "client_id": "client-123",
        "client_secret": "super-secret",
        "discovery_url": "https://accounts.google.com/.well-known/openid-configuration",
        "extra_params": {},
        "logo_key": "google",
        "is_enabled": True,
    }
    body.update(overrides)
    return body


async def test_public_sso_list_hides_secret_and_disabled(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    admin = await make_user(
        email="ssoadmin@dart.com", username="ssoadmin", password="AdminPass123!", is_superuser=True
    )
    token = await _login(client, admin.email, "AdminPass123!")

    created = await client.post(SSO_PUBLIC, json=_provider_body(), headers=_auth(token))
    assert created.status_code == 200
    disabled = await client.post(
        SSO_PUBLIC, json=_provider_body(provider_key="microsoft", is_enabled=False), headers=_auth(token)
    )
    assert disabled.status_code == 200

    public = await client.get(SSO_PUBLIC)
    assert public.status_code == 200
    keys = {row["provider_key"] for row in public.json()}
    assert "google" in keys
    assert "microsoft" not in keys
    google = next(row for row in public.json() if row["provider_key"] == "google")
    assert "client_secret" not in google
    assert google["client_id"] == "client-123"


async def test_sso_upsert_toggle_delete(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="ssomgr@dart.com", username="ssomgr", password="AdminPass123!", is_superuser=True
    )
    token = await _login(client, "ssomgr@dart.com", "AdminPass123!")

    saved = await client.post(SSO_PUBLIC, json=_provider_body(), headers=_auth(token))
    assert saved.status_code == 200

    listed = await client.get(SSO_MANAGE, headers=_auth(token))
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["has_secret"] is True
    assert "client_secret" not in row

    toggled = await client.post(f"{SSO_PUBLIC}/google/toggle", headers=_auth(token))
    assert toggled.status_code == 200
    assert toggled.json()["is_enabled"] is False

    deleted = await client.delete(f"{SSO_PUBLIC}/google", headers=_auth(token))
    assert deleted.status_code == 204
    empty = await client.get(SSO_MANAGE, headers=_auth(token))
    assert empty.json() == []


async def test_sso_manage_forbidden_without_privilege(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="plain@dart.com", username="plain", password="PlainPass123!")
    token = await _login(client, "plain@dart.com", "PlainPass123!")
    listed = await client.get(SSO_MANAGE, headers=_auth(token))
    assert listed.status_code == 403


async def test_sso_exchange_unknown_provider(client: AsyncClient) -> None:
    response = await client.post(
        SSO_EXCHANGE,
        json={
            "provider_key": "missing",
            "code": "abc",
            "code_verifier": "verifier",
            "redirect_uri": "http://localhost:3000/sso-callback",
        },
    )
    assert response.status_code == 400


async def test_sso_exchange_issues_tokens_for_existing_user(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_user(
        email="ssoadmin2@dart.com", username="ssoadmin2", password="AdminPass123!", is_superuser=True
    )
    admin_token = await _login(client, "ssoadmin2@dart.com", "AdminPass123!")
    await client.post(SSO_PUBLIC, json=_provider_body(), headers=_auth(admin_token))
    await make_user(email="sso.user@dart.com", username="ssouser", password="UserPass123!")

    async def _fake_exchange(**_kwargs: object) -> OidcIdentity:
        return OidcIdentity(email="sso.user@dart.com")

    monkeypatch.setattr("app.api.v1.endpoints.sso.exchange_authorization_code", _fake_exchange)

    exchanged = await client.post(
        SSO_EXCHANGE,
        json={
            "provider_key": "google",
            "code": "auth-code",
            "code_verifier": "verifier",
            "redirect_uri": "http://localhost:3000/sso-callback",
        },
    )
    assert exchanged.status_code == 200
    body = exchanged.json()
    assert body["access_token"]
    assert body["refresh_token"]

    logs = await client.get(SSO_AUDIT, headers=_auth(admin_token))
    assert logs.status_code == 200
    assert any(row["email"] == "sso.user@dart.com" and row["success"] for row in logs.json())


async def test_sso_exchange_unknown_email(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await make_user(
        email="ssoadmin3@dart.com", username="ssoadmin3", password="AdminPass123!", is_superuser=True
    )
    token = await _login(client, "ssoadmin3@dart.com", "AdminPass123!")
    await client.post(SSO_PUBLIC, json=_provider_body(), headers=_auth(token))

    async def _fake_exchange(**_kwargs: object) -> OidcIdentity:
        return OidcIdentity(email="nobody@dart.com")

    monkeypatch.setattr("app.api.v1.endpoints.sso.exchange_authorization_code", _fake_exchange)

    exchanged = await client.post(
        SSO_EXCHANGE,
        json={
            "provider_key": "google",
            "code": "auth-code",
            "code_verifier": "verifier",
            "redirect_uri": "http://localhost:3000/sso-callback",
        },
    )
    assert exchanged.status_code == 401


async def test_audit_mode_toggle_and_login_flag(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="audit@dart.com", username="auditadmin", password="AdminPass123!", is_superuser=True
    )
    first = await client.post(LOGIN_URL, json={"email": "audit@dart.com", "password": "AdminPass123!"})
    assert first.status_code == 200
    assert first.json()["audit_status"] is False
    token = first.json()["access_token"]

    current = await client.get(AUDIT_MODE, headers=_auth(token))
    assert current.status_code == 200
    assert current.json()["enabled"] is False

    enabled = await client.post(AUDIT_MODE, json={"enabled": True}, headers=_auth(token))
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert enabled.json()["admin_name"] == "auditadmin"

    again = await client.post(LOGIN_URL, json={"email": "audit@dart.com", "password": "AdminPass123!"})
    assert again.json()["audit_status"] is True


async def test_group_global_variables(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
) -> None:
    await make_user(
        email="gvadmin@dart.com", username="gvadmin", password="AdminPass123!", is_superuser=True
    )
    token = await _login(client, "gvadmin@dart.com", "AdminPass123!")

    created_group = await client.post(GROUPS, json={"name": "Finance"}, headers=_auth(token))
    assert created_group.status_code == 201
    group_id = created_group.json()["id"]

    created_gv = await client.post(GVS, json={"name": "FX_RATE"}, headers=_auth(token))
    assert created_gv.status_code == 201

    catalog = await client.get(GVS, headers=_auth(token))
    assert "FX_RATE" in [row["name"] for row in catalog.json()]

    linked = await client.post(
        f"{GROUPS}/{group_id}/global-variables", json={"name": "FX_RATE"}, headers=_auth(token)
    )
    assert linked.status_code == 204

    created_on_link = await client.post(
        f"{GROUPS}/{group_id}/global-variables", json={"name": "TAX_PCT"}, headers=_auth(token)
    )
    assert created_on_link.status_code == 204

    details = await client.get(f"{GROUPS}/{group_id}/details", headers=_auth(token))
    assert details.status_code == 200
    assert sorted(details.json()["gv_names"]) == ["FX_RATE", "TAX_PCT"]

    await client.delete(f"{GROUPS}/{group_id}/global-variables/FX_RATE", headers=_auth(token))
    details = await client.get(f"{GROUPS}/{group_id}/details", headers=_auth(token))
    assert details.json()["gv_names"] == ["TAX_PCT"]
