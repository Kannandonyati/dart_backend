"""User Maintenance — invite and admin-mediated password reset.
Replaces the old backend's `manage_users` app (`user/invite`,
`forgot/password`, `reset/password`, `invite/list`). `delete/user`'s
replacement (`DELETE /users/{id}`) lives in users.py alongside the rest
of core User CRUD, not here.

**Admin-mediated, not self-service email — a deliberate, security-
motivated deviation from the old backend, not a straight port.** This
codebase has no SMTP/email-sending integration (confirmed: nothing in
app/core/config.py configures one), so a true self-service "forgot
password" endpoint would have to either (a) not exist, or (b) hand a
password-reset token directly back to an *unauthenticated* caller who
merely claims an email address — which is a live account-takeover
vulnerability, not a documented gap, and this project does not ship
those. Instead: an admin (`user:manage`) generates an invite or
reset token through a privileged endpoint and delivers it to the user
out-of-band (however admins already communicate with users today); the
user then redeems that token through a public endpoint, the same
bearer-token-redemption model a real self-service flow would use for
the redemption half. The only real gap versus a production self-service
flow is *delivery* (manual instead of emailed) — a small, independent
follow-up once an email integration exists, not a redesign.

Invite/reset tokens are short-lived signed JWTs (app/core/security.py's
existing `TokenType`), not a separate revocable token table — same
trade-off already accepted for access/refresh tokens (see that module's
docstring): a leaked token is valid until it expires, and there's no
revocation store yet. Documented as a known gap in KT_PHASE9.md, not
new to this phase.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.audit import record_audit_log
from app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from app.core.permissions import require_privilege
from app.core.security import (
    InvalidTokenError,
    TokenType,
    create_invite_token,
    create_password_reset_token,
    decode_token,
    hash_password,
)
from app.core.usernames import derive_unique_username
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, build_pagination_meta
from app.schemas.user import UserRead
from app.schemas.user_maintenance import (
    InviteAccept,
    PasswordResetSubmit,
    PasswordResetTokenRead,
    UserInviteCreate,
    UserInviteRead,
)

router = APIRouter(prefix="/users", tags=["user-maintenance"])


@router.post(
    "/invite",
    response_model=UserInviteRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_privilege("user:manage")],
)
async def invite_user(
    body: UserInviteCreate, current_user: CurrentUser, db: DbSession
) -> UserInviteRead:
    """`resend=True` regenerates a fresh token for an existing, still-
    pending invite instead of creating a new account — matches the
    reference frontend's "Resend invite" action. Without an email
    integration, there's no other way to get a lost/expired invite link
    back in front of the invitee: rejecting it with the same 409 a
    genuinely-new invite to that email would get is the wrong answer, and
    creating a second `User` row for the same email is worse."""
    if body.resend:
        existing_row = (
            await db.execute(select(User).where(User.email == body.email))
        ).scalar_one_or_none()
        if existing_row is None:
            raise NotFoundError("No pending invite found for this email.")
        if existing_row.invite_accepted_at is not None:
            raise ConflictError("This user has already accepted their invite.")
        await record_audit_log(
            db,
            actor_user_id=current_user.id,
            action="user.invite_resent",
            entity_type="user",
            entity_id=str(existing_row.id),
            detail={"email": existing_row.email},
        )
        await db.commit()
        return UserInviteRead(
            user_id=str(existing_row.id),
            email=existing_row.email,
            username=existing_row.username,
            invite_token=create_invite_token(str(existing_row.id)),
        )

    username = body.username or await derive_unique_username(db, body.email)
    existing = await db.execute(
        select(User.id).where((User.email == body.email) | (User.username == username))
    )
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("A user with this email or username already exists.")

    user = User(
        email=body.email,
        username=username,
        # A real Argon2 hash of an unguessable, never-revealed random
        # value — NOT a sentinel string. passlib's verify() raises
        # UnknownHashError (surfacing as a 500) on a string that isn't
        # a hash it recognizes, so login must still be able to run a
        # normal, valid comparison; it just always fails until the
        # invite is redeemed and a real password is set.
        hashed_password=hash_password(uuid.uuid4().hex),
        is_active=False,
        # Left NULL on purpose — see User.invite_accepted_at's docstring.
        # accept_invite() below is the only thing that ever sets it.
    )
    db.add(user)
    await db.flush()
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="user.invited",
        entity_type="user",
        entity_id=str(user.id),
        detail={"email": user.email},
    )
    await db.commit()
    return UserInviteRead(
        user_id=str(user.id),
        email=user.email,
        username=user.username,
        invite_token=create_invite_token(str(user.id)),
    )


_INVITED_USERS_FILTER = (User.invite_accepted_at.is_(None), User.deleted_at.is_(None))


@router.get(
    "/invited",
    response_model=PaginatedResponse[UserRead],
    dependencies=[require_privilege("user:manage")],
)
async def list_invited_users(
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> PaginatedResponse[UserRead]:
    """Users who've been invited but haven't redeemed their invite yet —
    replaces the old backend's `invite/list` (`nonregistered_user_list`).
    The registered/active equivalent is `GET /users`, which excludes these
    same rows (see that endpoint's comment).

    Filters on `invite_accepted_at`, not `is_active` — `is_active=False`
    alone can't tell "never redeemed their invite" apart from "was
    deleted" (`DELETE /users/{id}`, users.py, also sets it False). Also
    excludes deleted users outright, same as GET /users.

    Returns the same `{data, pagination}` envelope as GET /users, with a
    real total_count — see app/schemas/pagination.py's module docstring."""
    total_count = (
        await db.execute(select(func.count()).select_from(User).where(*_INVITED_USERS_FILTER))
    ).scalar_one()
    stmt = (
        select(User)
        .where(*_INVITED_USERS_FILTER)
        .order_by(User.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    return PaginatedResponse(
        data=list((await db.execute(stmt)).scalars().all()),
        pagination=build_pagination_meta(
            page=pagination["page"],
            page_size=pagination["page_size"],
            offset=pagination["offset"],
            total_count=total_count,
        ),
    )


@router.post("/accept-invite", response_model=UserRead)
async def accept_invite(body: InviteAccept, db: DbSession) -> User:
    try:
        payload = decode_token(body.invite_token, expected_type=TokenType.INVITE)
    except InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired invite token") from exc

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise UnauthorizedError("Invalid or expired invite token")

    user.hashed_password = hash_password(body.password)
    user.is_active = True
    user.invite_accepted_at = datetime.now(UTC)
    await record_audit_log(
        db,
        actor_user_id=user.id,
        action="user.invite_accepted",
        entity_type="user",
        entity_id=str(user.id),
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.post(
    "/{user_id}/reset-token",
    response_model=PasswordResetTokenRead,
    dependencies=[require_privilege("user:manage")],
)
async def generate_password_reset_token(
    user_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> PasswordResetTokenRead:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="user.reset_token_generated",
        entity_type="user",
        entity_id=str(user.id),
    )
    await db.commit()
    return PasswordResetTokenRead(
        user_id=str(user.id), reset_token=create_password_reset_token(str(user.id))
    )


@router.post("/reset-password", response_model=UserRead)
async def reset_password(body: PasswordResetSubmit, db: DbSession) -> User:
    try:
        payload = decode_token(body.reset_token, expected_type=TokenType.PASSWORD_RESET)
    except InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired reset token") from exc

    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None:
        raise UnauthorizedError("Invalid or expired reset token")

    user.hashed_password = hash_password(body.new_password)
    await record_audit_log(
        db,
        actor_user_id=user.id,
        action="user.password_reset",
        entity_type="user",
        entity_id=str(user.id),
    )
    await db.commit()
    await db.refresh(user)
    return user
