"""Liveness/readiness checks for every piece of infra this service depends
on. Split into cheap sub-checks so a load balancer's liveness probe (just
"is the process up") doesn't need to touch the DB, while a readiness probe
or an on-call dashboard can hit /health/detailed to see exactly which
dependency is down instead of a single opaque failure."""

import structlog
from fastapi import APIRouter

from app.cache.redis import ping as redis_ping
from app.db.session import check_db_connection
from app.schemas.common import HealthComponent, HealthResponse

router = APIRouter(prefix="/health", tags=["health"])
logger = structlog.get_logger(__name__)


@router.get("", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok", components=[])


@router.get("/detailed", response_model=HealthResponse)
async def detailed_health() -> HealthResponse:
    components: list[HealthComponent] = []

    try:
        await check_db_connection()
        components.append(HealthComponent(name="postgres", ok=True))
    except Exception as exc:
        logger.warning("health_check_failed", component="postgres", error=str(exc))
        components.append(HealthComponent(name="postgres", ok=False, detail="unreachable"))

    try:
        ok = await redis_ping()
        components.append(HealthComponent(name="redis", ok=ok))
    except Exception as exc:
        logger.warning("health_check_failed", component="redis", error=str(exc))
        components.append(HealthComponent(name="redis", ok=False, detail="unreachable"))

    overall = "ok" if all(c.ok for c in components) else "degraded"
    return HealthResponse(status=overall, components=components)
