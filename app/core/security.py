"""Password hashing and JWT issuing/verification.

Argon2 (not bcrypt) is the password hash: it's the current OWASP-recommended
default and has no 72-byte input truncation footgun. Access tokens are
7 days by default (see Settings.access_token_expire_days); refresh
tokens last 1 day and must be checked against a revocation store
(e.g. Redis, by jti) by the caller — this module only handles
signing/verifying, not revocation state, which belongs with whatever calls
it once a real user store exists.
"""

import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"
    INVITE = "invite"
    PASSWORD_RESET = "password_reset"  # noqa: S105 -- token type name, not a credential


class InvalidTokenError(Exception):
    """Raised for any token that fails signature, expiry, or type checks."""


def hash_password(plain_password: str) -> str:
    return str(_pwd_context.hash(plain_password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bool(_pwd_context.verify(plain_password, hashed_password))


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),  # unique per token, enables single-token revocation
    }
    return str(jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm))


def create_access_token(subject: str) -> str:
    return _create_token(
        subject,
        TokenType.ACCESS,
        timedelta(days=settings.access_token_expire_days),
    )


def create_refresh_token(subject: str) -> str:
    return _create_token(
        subject,
        TokenType.REFRESH,
        timedelta(days=settings.refresh_token_expire_days),
    )


def create_invite_token(subject: str) -> str:
    return _create_token(
        subject,
        TokenType.INVITE,
        timedelta(days=settings.invite_token_expire_days),
    )


def create_password_reset_token(subject: str) -> str:
    return _create_token(
        subject,
        TokenType.PASSWORD_RESET,
        timedelta(hours=settings.password_reset_token_expire_hours),
    )


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    """Decode + validate a JWT. Raises InvalidTokenError on any failure —
    callers should treat that as an unauthenticated request, never leak the
    underlying jose exception detail back to the client."""
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as exc:
        raise InvalidTokenError("Token signature/expiry check failed") from exc

    if payload.get("type") != expected_type.value:
        raise InvalidTokenError(f"Expected a {expected_type.value} token")

    return payload
