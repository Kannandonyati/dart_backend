"""WebSocket endpoint scaffolding.

One generic, authenticated `/ws/{channel}` endpoint — the connect → auth
→ subscribe → receive-broadcast round trip is the same regardless of
what a channel means. Ownership scoping is channel-specific, added as
each real job type lands: `bridge_run:{id}` (Phase 6: Bridge Members,
app/tasks/bridge_tasks.py) is the first, checked via the same
`get_accessible_recon` every HTTP endpoint on that job's recon already
uses — a channel name alone must not be enough to see another user's
job progress. Any other channel name is still unscoped, same as before;
scope the next real job type here the same way when it lands.
"""

import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException, status
from sqlalchemy import select

from app.api.deps import get_current_user_ws
from app.core.exceptions import AppError
from app.core.recon_access import get_accessible_recon
from app.db.session import async_session_factory
from app.models.bridge import BridgeRun
from app.models.user import User
from app.ws.connection_manager import manager

router = APIRouter(tags=["websocket"])
logger = structlog.get_logger(__name__)


async def _check_channel_access(channel: str, user_id: uuid.UUID) -> None:
    if not channel.startswith("bridge_run:"):
        return
    raw_id = channel.removeprefix("bridge_run:")
    try:
        bridge_run_id = uuid.UUID(raw_id)
    except ValueError as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid channel"
        ) from exc

    async with async_session_factory() as db:
        run = (
            await db.execute(select(BridgeRun).where(BridgeRun.id == bridge_run_id))
        ).scalar_one_or_none()
        if run is None:
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Not found")

        current_user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
        try:
            await get_accessible_recon(db, current_user, run.recon_id)
        except AppError as exc:
            raise WebSocketException(
                code=status.WS_1008_POLICY_VIOLATION, reason=exc.message
            ) from exc


@router.websocket("/ws/{channel}")
async def websocket_endpoint(websocket: WebSocket, channel: str) -> None:
    user = await get_current_user_ws(websocket)
    await _check_channel_access(channel, user.id)
    await manager.connect(websocket, channel)
    logger.info("ws_subscribed", channel=channel, user=str(user.id))
    try:
        while True:
            # Inbound messages aren't part of the scaffolding contract yet
            # (this channel is server → client progress/notifications) —
            # received but not acted on, so the connection stays open and
            # a client ping/keepalive doesn't get treated as an error.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)
