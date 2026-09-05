"""Real authentication against the User table.

Two login routes, one shared check:
- `/auth/token` — OAuth2 form-encoded, exists so Swagger's built-in
  "Authorize" button (which only speaks OAuth2PasswordRequestForm) works.
- `/auth/login` — plain JSON, the one real clients (the frontend,
  Postman) should use.

Security properties worth being explicit about:
- **Timing-attack resistant**: password verification always runs, even
  when no user matches the email, against a fixed dummy hash — so a
  request for a nonexistent email takes the same time as one for a real
  email with a wrong password. Skipping verification on "user not found"
  would let a caller enumerate valid emails by timing alone.
- **Same error for every failure mode**: wrong email, wrong password, and
  inactive account all return the identical generic message. Distinct
  messages ("no such user" vs "wrong password") are themselves an
  enumeration oracle.
- **Rate-limited tighter than the global default** (`5/minute` per IP,
  vs. the app-wide 100/minute) — the endpoint an online guesser actually
  wants hit hardest gets the tightest limit, not a blanket one sized for
  normal traffic.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import DbSession, load_active_user
from app.core.audit import record_audit_log
from app.core.audit_mode import current_audit_status
from app.core.exceptions import UnauthorizedError
from app.core.system_log import record_system_log
from app.core.rate_limit import limiter
from app.core.security import (
    InvalidTokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import LoginRequest
from app.schemas.common import RefreshRequest, Token

router = APIRouter(prefix="/auth", tags=["auth"])

# A real Argon2 hash of a value nobody will ever type, computed once at
# import time — not a live user's hash, just a fixed cost to verify
# against so "user not found" and "wrong password" take the same time.
_DUMMY_HASH = hash_password("dummy-hash-for-constant-time-comparison-only")


async def _authenticate(db: DbSession, email: str, password: str) -> User:
    stmt = select(User).where(User.email == email.lower())
    user = (await db.execute(stmt)).scalar_one_or_none()

    hash_to_check = user.hashed_password if user is not None else _DUMMY_HASH
    password_ok = verify_password(password, hash_to_check)

    if user is None or not password_ok or not user.is_active:
        raise UnauthorizedError("Invalid email or password", code="invalid_credentials")
    return user


@router.post("/token", response_model=Token)
@limiter.limit("5/minute")
async def issue_token(
    request: Request,  # required by slowapi's @limiter.limit — unused otherwise
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
) -> Token:
    user = await _authenticate(db, form.username, form.password)
    return Token(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        audit_status=await current_audit_status(db),
    )


@router.post("/login", response_model=Token)
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: DbSession) -> Token:
    user = await _authenticate(db, body.email, body.password)
    # No recon_id — matches the reference system's own auth-event rows,
    # which show "N/A" for Event Stage/recon since a login isn't scoped
    # to any one recon.
    await record_audit_log(
        db,
        actor_user_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=str(user.id),
    )
    await db.commit()
    request_id = getattr(request.state, "request_id", None)
    await record_system_log(
        log_name="userlog",
        logging_level="INFO",
        log_message=f"{user.username} authenticated",
        request_url=request.url.path,
        request_id=str(request_id) if request_id else None,
        username=user.username,
        user_email=user.email,
        actor_user_id=user.id,
        event_stage="N/A",
    )
    return Token(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        audit_status=await current_audit_status(db),
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    body: RefreshRequest,
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Token:
    """Mint a new access+refresh pair. Prefer a still-valid refresh
    token; if that JWT is expired or missing, a still-valid access
    token in Authorization is enough. Both dead → 401 (client logs out)."""
    payload = None
    if body.refresh_token:
        try:
            payload = decode_token(body.refresh_token, expected_type=TokenType.REFRESH)
        except InvalidTokenError:
            payload = None

    if payload is None:
        access = _bearer_token(authorization)
        if access is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )
        try:
            payload = decode_token(access, expected_type=TokenType.ACCESS)
        except InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            ) from exc

    # Re-verify the user still exists and is active — a token issued
    # before an account was deactivated must not mint a fresh pair.
    user = await load_active_user(db, payload["sub"])

    # NOTE: this issues a new refresh token without revoking the old one.
    # Once a revocation store exists (Redis, keyed by jti), check the
    # incoming token's jti isn't revoked, and revoke it here before
    # issuing the replacement, so a stolen refresh token can't be reused
    # indefinitely in parallel with the legitimate one.
    return Token(
        access_token=create_access_token(str(user.id)),
        refresh_token=create_refresh_token(str(user.id)),
        audit_status=await current_audit_status(db),
    )


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token
