"""Auth endpoint tests — every security property called out in
app/api/v1/endpoints/auth.py's docstring gets its own test here, not
just the happy path."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

LOGIN_URL = "/api/v1/auth/login"


async def test_login_succeeds_with_correct_credentials(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="CorrectHorse123!")
    response = await client.post(
        LOGIN_URL, json={"email": "a@dart.com", "password": "CorrectHorse123!"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_fails_with_wrong_password(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="CorrectHorse123!")
    response = await client.post(LOGIN_URL, json={"email": "a@dart.com", "password": "wrong"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_login_fails_for_nonexistent_email_with_identical_error(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """The response for 'no such user' and 'wrong password' must be
    byte-for-byte identical — any difference is an account-enumeration
    oracle. See auth.py's module docstring."""
    await make_user(email="a@dart.com", username="a", password="CorrectHorse123!")

    wrong_password_response = await client.post(
        LOGIN_URL, json={"email": "a@dart.com", "password": "wrong"}
    )
    nonexistent_response = await client.post(
        LOGIN_URL, json={"email": "nobody@dart.com", "password": "wrong"}
    )

    assert wrong_password_response.status_code == nonexistent_response.status_code == 401
    wrong_password_error = wrong_password_response.json()["error"]
    nonexistent_error = nonexistent_response.json()["error"]
    assert wrong_password_error["code"] == nonexistent_error["code"] == "invalid_credentials"
    assert wrong_password_error["message"] == nonexistent_error["message"]


async def test_login_fails_for_inactive_user(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(
        email="inactive@dart.com", username="inactive", password="Password123!", is_active=False
    )
    response = await client.post(
        LOGIN_URL, json={"email": "inactive@dart.com", "password": "Password123!"}
    )
    assert response.status_code == 401


async def test_login_email_is_case_insensitive(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="mixedcase@dart.com", username="mc", password="Password123!")
    response = await client.post(
        LOGIN_URL, json={"email": "MixedCase@Dart.com", "password": "Password123!"}
    )
    assert response.status_code == 200


async def test_refresh_issues_new_access_token(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    login = await client.post(LOGIN_URL, json={"email": "a@dart.com", "password": "Password123!"})
    refresh_token = login.json()["refresh_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_tokens_last_seven_days_access_and_one_day_refresh(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="ttl@dart.com", username="ttl", password="Password123!")
    login = await client.post(LOGIN_URL, json={"email": "ttl@dart.com", "password": "Password123!"})
    from jose import jwt

    from app.core.config import settings

    access = jwt.decode(
        login.json()["access_token"],
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    refresh = jwt.decode(
        login.json()["refresh_token"],
        settings.secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    assert access["exp"] - access["iat"] == 7 * 24 * 3600
    assert refresh["exp"] - refresh["iat"] == 1 * 24 * 3600


async def test_refresh_with_valid_access_token_when_refresh_is_expired(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """If the 1-day refresh JWT is dead but the 7-day access JWT is still
    valid, mint a new pair so the user is not logged out."""
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.core.config import settings

    user = await make_user(email="rot@dart.com", username="rot", password="Password123!")
    login = await client.post(LOGIN_URL, json={"email": "rot@dart.com", "password": "Password123!"})
    access_token = login.json()["access_token"]
    now = datetime.now(UTC)
    expired_refresh = jwt.encode(
        {
            "sub": str(user.id),
            "type": "refresh",
            "iat": now - timedelta(days=2),
            "exp": now - timedelta(hours=1),
            "jti": "expired-refresh",
        },
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": expired_refresh},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]
    assert response.json()["refresh_token"]


async def test_refresh_logs_out_when_both_tokens_are_expired(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.core.config import settings

    user = await make_user(email="both@dart.com", username="both", password="Password123!")
    now = datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "iat": now - timedelta(days=8),
        "exp": now - timedelta(hours=1),
        "jti": "dead",
    }
    dead_access = jwt.encode(
        {**claims, "type": "access", "jti": "dead-access"},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )
    dead_refresh = jwt.encode(
        {**claims, "type": "refresh", "jti": "dead-refresh"},
        settings.secret_key,
        algorithm=settings.jwt_algorithm,
    )

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": dead_refresh},
        headers={"Authorization": f"Bearer {dead_access}"},
    )
    assert response.status_code == 401


async def test_refresh_rejects_an_access_token_used_as_refresh_token(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    """A token minted as `type: access` must not work at the refresh
    endpoint, even though it's a validly-signed token from this same
    issuer — type-confusion between token kinds is a real vulnerability
    class, not a theoretical one."""
    await make_user(email="a@dart.com", username="a", password="Password123!")
    login = await client.post(LOGIN_URL, json={"email": "a@dart.com", "password": "Password123!"})
    access_token = login.json()["access_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


async def test_refresh_rejects_deactivated_user(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], db_session: AsyncSession
) -> None:
    user = await make_user(email="a@dart.com", username="a", password="Password123!")
    login = await client.post(LOGIN_URL, json={"email": "a@dart.com", "password": "Password123!"})
    refresh_token = login.json()["refresh_token"]

    user.is_active = False
    db_session.add(user)
    await db_session.commit()

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401


async def test_login_rejects_malformed_email(client: AsyncClient) -> None:
    response = await client.post(LOGIN_URL, json={"email": "not-an-email", "password": "x"})
    assert response.status_code == 422


async def test_users_me_requires_authentication(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_users_me_rejects_garbage_token(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not.a.real.token"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_deactivating_a_user_immediately_invalidates_their_existing_token(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], db_session: AsyncSession
) -> None:
    """The core property get_current_user's real DB check exists for:
    a cryptographically valid, unexpired access token must stop working
    the moment the account is deactivated — not just at next expiry."""
    user = await make_user(email="a@dart.com", username="a", password="Password123!")
    login = await client.post(LOGIN_URL, json={"email": "a@dart.com", "password": "Password123!"})
    access_token = login.json()["access_token"]

    before = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert before.status_code == 200

    user.is_active = False
    db_session.add(user)
    await db_session.commit()

    after = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert after.status_code == 401


async def test_response_never_contains_hashed_password(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]]
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")
    login = await client.post(LOGIN_URL, json={"email": "a@dart.com", "password": "Password123!"})
    access_token = login.json()["access_token"]

    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert "hashed_password" not in response.text
    assert "password" not in response.json()
