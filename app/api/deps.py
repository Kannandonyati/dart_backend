"""Shared FastAPI dependencies: DB session, Redis, and auth.

`get_current_user` decodes the JWT *and* re-checks the user against the
database on every request — not just the token signature. This matters:
a token is valid (signature + expiry) independent of whether the account
it names still exists or is still active, so trusting the token alone
would mean a deleted or deactivated user's existing access token keeps
working until it naturally expires. Re-checking on every request closes
that gap at the cost of one indexed primary-key lookup per request,
which is a good trade for auth.
"""

import uuid
from typing import Annotated

from fastapi import Depends, WebSocket, WebSocketException, status
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis import get_redis
from app.core.exceptions import UnauthorizedError
from app.core.security import InvalidTokenError, TokenType, decode_token
from app.db.session import async_session_factory, get_db
from app.models.user import User

# tokenUrl is where Swagger's "Authorize" button POSTs — matches the
# OAuth2-form login route in api/v1/endpoints/auth.py.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[Redis, Depends(get_redis)]


async def load_active_user(db: AsyncSession, subject: str) -> User:
    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        # A token whose `sub` isn't a UUID at all didn't come from our
        # own issuer with a real user id — treat identically to "not
        # found" rather than leaking the parse failure.
        raise UnauthorizedError("Invalid or expired token", code="invalid_token") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid or expired token", code="invalid_token")
    return user


async def get_current_user(
    token: Annotated[str | None, Depends(_oauth2_scheme)],
    db: DbSession,
) -> User:
    if token is None:
        raise UnauthorizedError("Not authenticated", code="not_authenticated")
    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired token", code="invalid_token") from exc
    return await load_active_user(db, payload["sub"])


async def get_current_user_ws(websocket: WebSocket) -> User:
    """WebSocket auth: browsers' native WebSocket API can't set custom
    headers on the handshake, so the token travels as a query param
    instead (`wss://.../ws/{channel}?token=...`). Documented trade-off:
    query params can end up in access logs — if that's unacceptable for
    a given deployment, switch this to reading an httpOnly session
    cookie set by the login flow instead.

    Opens its own short-lived DB session rather than taking one as a
    parameter — this is called directly from the websocket route
    (`await get_current_user_ws(websocket)`), not through FastAPI's
    `Depends`, since WebSocket routes don't go through the same
    dependency-injection request cycle HTTP routes do."""
    token = websocket.query_params.get("token")
    if token is None:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing token")
    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token"
        ) from exc
    try:
        async with async_session_factory() as db:
            return await load_active_user(db, payload["sub"])
    except UnauthorizedError as exc:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=exc.message) from exc


async def get_optional_user(
    token: Annotated[str | None, Depends(_oauth2_scheme)],
    db: DbSession,
) -> User | None:
    """Same lookup as `get_current_user`, but missing/invalid credentials
    become `None` instead of 401. Used by router-level guards that must
    not invent an auth requirement the route itself doesn't have — e.g.
    the UI-component closer on `/users/*`, which would otherwise 401
    public invite/password-reset redemption."""
    if token is None:
        return None
    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
        return await load_active_user(db, payload["sub"])
    except (InvalidTokenError, UnauthorizedError):
        return None


# Re-exported here so route modules only need one import line for the
# common dependency trio (db session, redis, current user).
CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]


async def get_pagination(page: int = 1, page_size: int = 25) -> dict[str, int]:
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)  # hard ceiling — no unbounded page_size DoS
    return {"page": page, "page_size": page_size, "offset": (page - 1) * page_size}
