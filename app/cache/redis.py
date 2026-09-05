"""Async Redis client + thin cache helpers.

One Redis instance, two jobs (see architecture.md): this module owns the
cache-and-pub/sub connection; app.tasks.celery_app owns Celery's own
broker/result-backend connections separately (Celery manages its own sync
connection pool internally — mixing that with this async client would
gain nothing and complicate shutdown).
"""

from collections.abc import AsyncGenerator
from typing import Any

import orjson
import structlog
from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

logger = structlog.get_logger(__name__)

# On Windows, `localhost` resolves to ::1 first. Redis is usually bound
# only to 127.0.0.1, so the IPv6 attempt hangs (no timeout by default)
# and every Redis-backed request — including login rate-limiting — never
# returns. Force IPv4 and fail fast.
_REDIS_SOCKET_TIMEOUT = 1.0


def resolve_loopback_url(url: str) -> str:
    """Windows resolves `localhost` to ::1 first. Prefer IPv4."""
    return url.replace("://localhost", "://127.0.0.1").replace(
        "@localhost:", "@127.0.0.1:"
    )


def resolve_redis_url(url: str) -> str:
    return resolve_loopback_url(url)


_pool = ConnectionPool.from_url(
    resolve_redis_url(str(settings.redis_url)),
    decode_responses=True,
    socket_connect_timeout=_REDIS_SOCKET_TIMEOUT,
    socket_timeout=_REDIS_SOCKET_TIMEOUT,
)


def get_redis_client() -> Redis:
    return Redis(connection_pool=_pool)


async def get_redis() -> AsyncGenerator[Redis]:
    """FastAPI dependency form of get_redis_client — inject with
    `redis: Redis = Depends(get_redis)` in any route/service that needs
    caching."""
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def cache_get_json(redis: Redis, key: str) -> dict[str, Any] | list[Any] | None:
    raw = await redis.get(key)
    if raw is None:
        return None
    result: dict[str, Any] | list[Any] = orjson.loads(raw)
    return result


async def cache_set_json(
    redis: Redis, key: str, value: dict[str, Any] | list[Any], *, ttl_seconds: int | None = None
) -> None:
    await redis.set(key, orjson.dumps(value), ex=ttl_seconds or settings.redis_cache_ttl_seconds)


async def cache_delete(redis: Redis, *keys: str) -> None:
    if keys:
        await redis.delete(*keys)


async def ping() -> bool:
    """Used by the /health/redis check — cheap, no side effects."""
    client = get_redis_client()
    try:
        return bool(await client.ping())
    finally:
        await client.aclose()
