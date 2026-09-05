"""The rate limiter is disabled app-wide for ENVIRONMENT=test (see
app/core/rate_limit.py) so the rest of the suite can call /auth/login
freely without tripping it — that's normal test traffic, not an attack.
This file is the one place that deliberately re-enables it, to prove the
limiter itself actually blocks excess requests rather than just trusting
slowapi's config to do the right thing."""

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.core.rate_limit import limiter
from app.models.user import User


@pytest.fixture
def _rate_limiting_enabled():
    limiter.enabled = True
    yield
    limiter.enabled = False


async def test_login_is_rate_limited_after_five_attempts_per_minute(
    client: AsyncClient, make_user: Callable[..., Awaitable[User]], _rate_limiting_enabled: None
) -> None:
    await make_user(email="a@dart.com", username="a", password="Password123!")

    statuses = []
    for _ in range(7):
        response = await client.post(
            "/api/v1/auth/login", json={"email": "a@dart.com", "password": "wrong"}
        )
        statuses.append(response.status_code)

    # First 5 are evaluated normally (all 401 — wrong password); the 6th
    # and 7th must be rejected by the limiter before touching auth logic.
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
    assert statuses[6] == 429
