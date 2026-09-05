"""Startup checks must refuse to boot when Redis or the queue broker is down.

Local/test environments used to warn and continue for those two; they
are now hard failures in every environment, same as Postgres.
"""

from unittest.mock import AsyncMock

import pytest

from app.core.startup import StartupCheckFailed, run_startup_checks


async def test_unreachable_redis_and_queue_fail_startup_when_not_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.core.startup.check_db_connection", AsyncMock(return_value=None)
    )
    monkeypatch.setattr("app.core.startup.cache_ping", AsyncMock(return_value=False))

    class _BrokerDown:
        @classmethod
        def from_url(cls, *_args: object, **_kwargs: object) -> "_BrokerDown":
            return cls()

        async def ping(self) -> bool:
            return False

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("app.core.startup.Redis", _BrokerDown)
    monkeypatch.setattr(
        "app.core.startup.settings.strict_startup_checks", False, raising=False
    )

    with pytest.raises(StartupCheckFailed, match="redis_cache") as exc_info:
        await run_startup_checks()
    assert "queue_broker" in str(exc_info.value)
