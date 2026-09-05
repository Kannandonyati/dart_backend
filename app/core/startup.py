"""Startup dependency checks.

Each dependency below is marked `mandatory` or not. A mandatory check
always fails startup on error, in every environment. Postgres, Redis
cache, and the Celery Redis broker are all mandatory: the app is not
meaningfully usable without them, so there is no value in starting
"successfully" against a stack that isn't there.

`Settings.enforce_strict_startup` still makes *every* check strict
regardless of `mandatory` — reserved for any future optional dependency
that should only be hard in staging/production.
"""

from collections.abc import Awaitable, Callable

import structlog
from redis.asyncio import Redis

from app.cache.redis import resolve_redis_url, ping as cache_ping
from app.core.colors import GREEN, RED, YELLOW, colorize
from app.core.config import settings
from app.db.session import check_db_connection

logger = structlog.get_logger(__name__)


class StartupCheckFailed(RuntimeError):
    pass


async def _check_database() -> None:
    await check_db_connection()


async def _check_cache() -> None:
    if not await cache_ping():
        raise StartupCheckFailed("Redis cache did not respond to PING")


async def _check_queue_broker() -> None:
    # The queue broker is Redis too (architecture.md §4) — a plain PING
    # against that URL is enough to confirm it's reachable at boot; Celery
    # itself opens its own connections lazily per-worker, this just proves
    # the broker process is up before the API claims to be ready.
    client: Redis = Redis.from_url(
        resolve_redis_url(str(settings.celery_broker_url)),
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    try:
        if not await client.ping():
            raise StartupCheckFailed("Celery broker (Redis) did not respond to PING")
    finally:
        await client.aclose()


def _redact(url: str) -> str:
    """Never log a connection string with embedded credentials verbatim."""
    if "@" in url:
        scheme, _, rest = url.partition("://")
        _, _, host_part = rest.partition("@")
        return f"{scheme}://***:***@{host_part}"
    return url


_CHECKS: list[tuple[str, Callable[[], Awaitable[None]], str, bool]] = [
    ("database", _check_database, _redact(str(settings.database_url)), True),
    ("redis_cache", _check_cache, _redact(str(settings.redis_url)), True),
    ("queue_broker", _check_queue_broker, _redact(str(settings.celery_broker_url)), True),
]


async def run_startup_checks() -> None:
    logger.info(
        "startup_checks_started",
        environment=settings.environment,
        strict=settings.enforce_strict_startup,
    )
    failures: list[str] = []
    hard_failures: list[str] = []

    for name, check, detail, mandatory in _CHECKS:
        try:
            await check()
        except Exception as exc:  # any dependency failure is handled the same way
            failures.append(name)
            event = f"{name}_check_failed"
            if mandatory or settings.enforce_strict_startup:
                hard_failures.append(name)
                logger.error(colorize(event, RED), detail=detail, error=str(exc))
            else:
                logger.warning(colorize(event, YELLOW), detail=detail, error=str(exc))
        else:
            logger.info(colorize(f"{name}_connected", GREEN), detail=detail)

    if hard_failures:
        logger.error(colorize("startup_checks_failed", RED), failed=hard_failures)
        raise StartupCheckFailed(f"Dependencies unreachable: {', '.join(hard_failures)}")

    if failures:
        logger.warning(
            colorize("startup_checks_incomplete", YELLOW),
            failed=failures,
            note="Starting anyway — these are non-mandatory locally. "
            "Endpoints touching them will fail until they're reachable.",
        )
    else:
        logger.info(colorize("startup_checks_passed", GREEN))
