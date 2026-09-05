"""Rate limiting, backed by the same Redis instance as the cache.

Storage is Redis, not in-memory — an in-memory limiter is per-process and
therefore useless the moment you run more than one uvicorn worker (each
worker would get its own independent limit). Redis-backed limits are
shared across every worker/instance, which is the only version that
actually protects anything once you scale past one process.

Per-route limits are applied with `@limiter.limit("5/minute")` on top of
the default from settings.rate_limit_default applied globally in main.py.

`in_memory_fallback_enabled=True` matters more than it looks: without it,
a Redis blip doesn't just weaken rate limiting, it crashes every request
with an unhandled error (confirmed while building this — slowapi's
exception handler assumes the storage backend only ever raises
`RateLimitExceeded`, and chokes on the `ConnectionError` a dead Redis
actually raises). With the fallback enabled, a Redis outage degrades to
a per-process in-memory limit instead of taking the whole API down —
weaker rate limiting during an outage is an acceptable trade, an
availability outage caused by the *rate limiter itself* is not.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.cache.redis import resolve_redis_url
from app.core.config import settings

# Local/test: in-memory buckets. Redis here is *synchronous* (slowapi)
# and would block the whole asyncio loop for tens of seconds if
# `localhost` hangs on IPv6 — that is what made POST /auth/login sit
# at "pending" in the browser. Staging/production still share Redis.
_limiter_storage = (
    "memory://"
    if settings.environment in ("local", "test")
    else resolve_redis_url(str(settings.redis_url))
)

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_limiter_storage,
    default_limits=[settings.rate_limit_default],
    in_memory_fallback_enabled=True,
    # The automated test suite legitimately calls the same endpoint
    # (e.g. /auth/login) far more than 5x/minute across many independent
    # tests, all sharing one in-memory limiter bucket in-process (no
    # Redis in the test environment) — that's normal test traffic, not
    # an attack, so rate limiting is disabled for it. Every other
    # environment, including local dev, keeps it on.
    enabled=settings.environment != "test",
)
