"""WebSocket connection manager with Redis pub/sub fan-out.

Why pub/sub instead of just holding connections in memory: once there is
more than one API instance behind a load balancer, a Celery worker
finishing a job doesn't know which instance holds the browser's socket.
Publishing progress to a Redis channel and having *every* instance
subscribe means any instance can deliver to any locally-connected client,
regardless of which instance originally handled that request — this is
the same Redis already used for caching (architecture.md §5).

Channels are logical groupings (e.g. `job:{job_id}` or `user:{user_id}`),
not raw Redis pub/sub channel names directly exposed to callers — callers
go through `broadcast()`/`connect()` with a channel string and this module
handles the Redis channel naming underneath.
"""

import asyncio
from collections import defaultdict
from typing import Any

import orjson
import structlog
from fastapi import WebSocket
from redis.asyncio import Redis

from app.cache.redis import get_redis_client

logger = structlog.get_logger(__name__)

_REDIS_CHANNEL_PREFIX = "ws:"


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._pubsub_task: asyncio.Task[None] | None = None
        self._redis: Redis | None = None

    async def connect(self, websocket: WebSocket, channel: str) -> None:
        await websocket.accept()
        self._connections[channel].add(websocket)
        logger.info("ws_connected", channel=channel, local_count=len(self._connections[channel]))

    def disconnect(self, websocket: WebSocket, channel: str) -> None:
        self._connections[channel].discard(websocket)
        if not self._connections[channel]:
            del self._connections[channel]
        logger.info("ws_disconnected", channel=channel)

    async def broadcast(self, channel: str, message: dict[str, Any]) -> None:
        """Publish to Redis — the running pub/sub listener (on this and
        every other instance) delivers it to locally-connected sockets.
        This is the only path messages take, even for same-instance
        delivery, so behavior is identical in single- and multi-instance
        deployments."""
        redis = get_redis_client()
        try:
            await redis.publish(_REDIS_CHANNEL_PREFIX + channel, orjson.dumps(message))
        finally:
            await redis.aclose()

    async def _deliver_local(self, channel: str, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections.get(channel, set()):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, channel)

    async def start_listener(self) -> None:
        """Run for the lifetime of the app (started in the lifespan
        handler). Subscribes to every ws:* channel and fans out to
        whichever local sockets are on that channel."""
        self._redis = get_redis_client()
        pubsub = self._redis.pubsub()
        await pubsub.psubscribe(f"{_REDIS_CHANNEL_PREFIX}*")
        logger.info("ws_pubsub_listener_started")
        try:
            async for message in pubsub.listen():
                if message["type"] != "pmessage":
                    continue
                channel = message["channel"].removeprefix(_REDIS_CHANNEL_PREFIX)
                payload = orjson.loads(message["data"])
                await self._deliver_local(channel, payload)
        except asyncio.CancelledError:
            await pubsub.punsubscribe()
            raise

    async def stop_listener(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
        if self._redis:
            await self._redis.aclose()


manager = ConnectionManager()
