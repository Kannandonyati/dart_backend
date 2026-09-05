"""Platform-admin tier and UI-component visibility."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ui_components import ALL_COMPONENTS, COMPONENTS_BY_KEY
from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"
VISIBILITY_URL = "/api/v1/ui-components/visibility"
CATALOG_URL = "/api/v1/ui-components"
ME_URL = "/api/v1/users/me"
RECONS_URL = "/api/v1/recons"
USERS_URL = "/api/v1/users"


async def _login(client: AsyncClient, email: str, password: str) -> str:
    response = await client.post(LOGIN_URL, json={"email": email, "password": password})
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_catalog_has_no_duplicate_or_dangling_keys() -> None:
    assert len(COMPONENTS_BY_KEY) == len(ALL_COMPONENTS)
    for component in ALL_COMPONENTS:
        if component.parent is not None:
            assert component.parent in COMPONENTS_BY_KEY


def test_public_user_redemption_paths_are_not_owned() -> None:
    from app.core.ui_components import components_for_api_path

    assert components_for_api_path("/users/me") == []
    assert components_for_api_path("/users/directory") == []
    assert components_for_api_path("/users/accept-invite") == []
    assert components_for_api_path("/users/reset-password") == []
    assert components_for_api_path("/users") != []
    assert components_for_api_path("/users/invite") != []


async def test_users_me_exposes_platform_admin_flag(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    token = await _login(client, "p@dart.com", "Password123!")
    me = await client.get(ME_URL, headers=_auth(token))
    assert me.status_code == 200
    body = me.json()
    assert body["is_platform_admin"] is True
    assert body["is_superuser"] is True


async def test_ordinary_superuser_is_not_a_platform_admin(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="s@dart.com", username="super", password="Password123!", is_superuser=True
    )
    token = await _login(client, "s@dart.com", "Password123!")
    me = (await client.get(ME_URL, headers=_auth(token))).json()
    assert me["is_superuser"] is True
    assert me["is_platform_admin"] is False

    catalog = await client.get(CATALOG_URL, headers=_auth(token))
    assert catalog.status_code == 403
    assert catalog.json()["error"]["code"] == "platform_admin_required"


async def test_new_user_sees_everything_except_the_platform_console(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    token = await _login(client, "a@dart.com", "Password123!")
    vis = (await client.get(VISIBILITY_URL, headers=_auth(token))).json()
    keys = set(vis["visible_keys"])
    assert vis["is_platform_admin"] is False
    assert "sidebar.general.recon-pipeline" in keys
    assert "sidebar.workflow-automation" in keys
    assert "sidebar.platform" not in keys
    assert "sidebar.platform.ui-components" not in keys


async def test_platform_admin_sees_the_console(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    token = await _login(client, "p@dart.com", "Password123!")
    vis = (await client.get(VISIBILITY_URL, headers=_auth(token))).json()
    assert vis["is_platform_admin"] is True
    assert "sidebar.platform.ui-components" in vis["visible_keys"]


async def test_disable_hides_from_everyone_but_platform_admin(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    await make_user(email="a@dart.com", username="a", password="Password123!")
    admin = await _login(client, "p@dart.com", "Password123!")
    user = await _login(client, "a@dart.com", "Password123!")

    updated = await client.put(
        f"{CATALOG_URL}/sidebar.workflow-automation",
        headers=_auth(admin),
        json={"is_enabled": False, "audience": "everyone"},
    )
    assert updated.status_code == 200
    entry = next(
        c
        for c in updated.json()["components"]
        if c["key"] == "sidebar.workflow-automation"
    )
    assert entry["enabled_for_everyone"] is False

    user_keys = set(
        (await client.get(VISIBILITY_URL, headers=_auth(user))).json()["visible_keys"]
    )
    admin_keys = set(
        (await client.get(VISIBILITY_URL, headers=_auth(admin))).json()["visible_keys"]
    )
    assert "sidebar.workflow-automation" not in user_keys
    assert "sidebar.workflow-automation.scheduler" not in user_keys
    assert "sidebar.workflow-automation" in admin_keys


async def test_user_type_override_beats_everyone_baseline(
    client: AsyncClient,
    make_user: Callable[..., Awaitable[User]],
    db_session: AsyncSession,
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    recon = await make_user(email="r@dart.com", username="recon", password="Password123!")
    recon.user_types = ["Recon User"]
    account = await make_user(email="a@dart.com", username="acct", password="Password123!")
    account.user_types = ["Account Admin"]
    await db_session.commit()

    admin = await _login(client, "p@dart.com", "Password123!")
    await client.put(
        f"{CATALOG_URL}/sidebar.workflow-automation",
        headers=_auth(admin),
        json={"is_enabled": False, "audience": "everyone"},
    )
    await client.put(
        f"{CATALOG_URL}/sidebar.workflow-automation",
        headers=_auth(admin),
        json={"is_enabled": True, "audience": "Account Admin"},
    )

    recon_token = await _login(client, "r@dart.com", "Password123!")
    account_token = await _login(client, "a@dart.com", "Password123!")
    recon_keys = set(
        (await client.get(VISIBILITY_URL, headers=_auth(recon_token))).json()["visible_keys"]
    )
    account_keys = set(
        (await client.get(VISIBILITY_URL, headers=_auth(account_token))).json()["visible_keys"]
    )
    assert "sidebar.workflow-automation" not in recon_keys
    assert "sidebar.workflow-automation" in account_keys


async def test_locked_component_cannot_be_disabled(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    token = await _login(client, "p@dart.com", "Password123!")
    response = await client.put(
        f"{CATALOG_URL}/sidebar.platform.ui-components",
        headers=_auth(token),
        json={"is_enabled": False},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "component_locked"


async def test_disabled_page_closes_its_api(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    await make_user(email="a@dart.com", username="a", password="Password123!")
    admin = await _login(client, "p@dart.com", "Password123!")
    user = await _login(client, "a@dart.com", "Password123!")

    await client.put(
        f"{CATALOG_URL}/sidebar.general.recon-pipeline",
        headers=_auth(admin),
        json={"is_enabled": False},
    )

    listed = await client.get(RECONS_URL, headers=_auth(user))
    assert listed.status_code == 403
    assert listed.json()["error"]["code"] == "component_disabled"

    # Platform admin is exempt, so they can still list recons — and
    # /users/me must keep working for the disabled user, otherwise they
    # couldn't even stay signed in.
    admin_list = await client.get(RECONS_URL, headers=_auth(admin))
    assert admin_list.status_code == 200
    me = await client.get(ME_URL, headers=_auth(user))
    assert me.status_code == 200


async def test_disabling_manage_users_does_not_block_me_or_directory(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    await make_user(email="a@dart.com", username="a", password="Password123!")
    admin = await _login(client, "p@dart.com", "Password123!")
    user = await _login(client, "a@dart.com", "Password123!")
    await client.put(
        f"{CATALOG_URL}/sidebar.general.manage-users",
        headers=_auth(admin),
        json={"is_enabled": False},
    )

    me = await client.get(ME_URL, headers=_auth(user))
    assert me.status_code == 200
    directory = await client.get(f"{USERS_URL}/directory", headers=_auth(user))
    assert directory.status_code == 200
    listed = await client.get(USERS_URL, headers=_auth(user))
    assert listed.status_code == 403


async def test_accept_invite_stays_public_when_manage_users_is_off(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """Router-level component guard must not invent an auth requirement
    on public token-redemption endpoints under /users."""
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    admin = await _login(client, "p@dart.com", "Password123!")
    invited = await client.post(
        f"{USERS_URL}/invite",
        headers=_auth(admin),
        json={"email": "invitee@dart.com", "username": "invitee"},
    )
    assert invited.status_code == 201
    await client.put(
        f"{CATALOG_URL}/sidebar.general.manage-users",
        headers=_auth(admin),
        json={"is_enabled": False},
    )
    accepted = await client.post(
        f"{USERS_URL}/accept-invite",
        json={
            "invite_token": invited.json()["invite_token"],
            "password": "InviteeRealPass123!",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["is_active"] is True


async def test_reset_returns_component_to_stock_visible(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    await make_user(email="a@dart.com", username="a", password="Password123!")
    admin = await _login(client, "p@dart.com", "Password123!")
    user = await _login(client, "a@dart.com", "Password123!")
    await client.put(
        f"{CATALOG_URL}/sidebar.other.ask-dart",
        headers=_auth(admin),
        json={"is_enabled": False},
    )
    hidden = set(
        (await client.get(VISIBILITY_URL, headers=_auth(user))).json()["visible_keys"]
    )
    assert "sidebar.other.ask-dart" not in hidden

    reset = await client.post(
        f"{CATALOG_URL}/sidebar.other.ask-dart/reset",
        headers=_auth(admin),
        json={"audience": "everyone"},
    )
    assert reset.status_code == 200
    visible = set(
        (await client.get(VISIBILITY_URL, headers=_auth(user))).json()["visible_keys"]
    )
    assert "sidebar.other.ask-dart" in visible


async def test_unknown_component_is_404(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="p@dart.com",
        username="plat",
        password="Password123!",
        is_platform_admin=True,
        is_superuser=True,
    )
    token = await _login(client, "p@dart.com", "Password123!")
    response = await client.put(
        f"{CATALOG_URL}/not.a.real.key",
        headers=_auth(token),
        json={"is_enabled": False},
    )
    assert response.status_code == 404
