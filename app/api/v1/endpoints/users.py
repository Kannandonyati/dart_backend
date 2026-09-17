"""User management — the first real, privilege-gated endpoints.

`POST /users` and `GET /users`/`GET /users/{id}` require the
`user:manage` privilege (seeded onto the "Account Admin" role by
app/db/seed.py); `GET /users/me` only requires being authenticated at
all, as any user should be able to read their own profile.
"""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, get_pagination
from app.core.audit import record_audit_log
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import require_privilege
from app.core.security import hash_password_async
from app.core.user_type_grants import sync_user_type_grants
from app.models.user import User
from app.schemas.pagination import PaginatedResponse, build_pagination_meta
from app.schemas.user import UserCreate, UserDirectoryEntry, UserRead, UserTypesUpdate

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserRead)
async def read_own_profile(current_user: CurrentUser) -> User:
    return current_user


@router.get("/directory", response_model=list[UserDirectoryEntry])
async def list_user_directory(_current_user: CurrentUser, db: DbSession) -> list[UserDirectoryEntry]:
    """Username picklist for Recon Security memberships. Authenticated
    only — old `users/email_list` was the same. Email is omitted."""
    stmt = (
        select(User)
        .where(*_LIST_USERS_FILTER)
        .order_by(User.username)
    )
    return [
        UserDirectoryEntry(id=user.id, username=user.username, user_types=list(user.user_types or []))
        for user in (await db.execute(stmt)).scalars().all()
    ]


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_privilege("user:manage")],
)
async def create_user(body: UserCreate, db: DbSession) -> User:
    existing = await db.execute(
        select(User.id).where((User.email == body.email) | (User.username == body.username))
    )
    if existing.scalar_one_or_none() is not None:
        # Deliberately doesn't say *which* field collided (email vs.
        # username) — that distinction is a minor account-enumeration
        # leak for no real benefit to a legitimate caller, who already
        # knows both values they just submitted.
        raise ConflictError("A user with this email or username already exists.")

    user = User(
        email=body.email,
        username=body.username,
        hashed_password=await hash_password_async(body.password),
        # Created directly, not via an invite that needs redeeming — see
        # User.invite_accepted_at's docstring.
        invite_accepted_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        # The check above is inherently check-then-act: two concurrent
        # requests for the same email/username can both pass it before
        # either commits. The unique constraint on users.email/username
        # is the real backstop for that race — without this catch, the
        # loser of the race gets an unhandled 500 instead of the same
        # clean 409 the first check already gives every other caller.
        await db.rollback()
        raise ConflictError("A user with this email or username already exists.") from exc
    await db.refresh(user)
    return user


_LIST_USERS_FILTER = (
    User.deleted_at.is_(None),
    or_(User.invite_accepted_at.is_not(None), User.is_active.is_(True)),
)


@router.get(
    "", response_model=PaginatedResponse[UserRead], dependencies=[require_privilege("user:manage")]
)
async def list_users(
    db: DbSession,
    pagination: Annotated[dict[str, int], Depends(get_pagination)],
) -> PaginatedResponse[UserRead]:
    # Excludes deleted users outright (see User.deleted_at's docstring),
    # and excludes users who were invited but never redeemed that invite
    # — they belong in GET /users/invited (Phase 9), not here. A user
    # with invite_accepted_at set (redeemed, or created directly/seeded)
    # always qualifies regardless of is_active.
    #
    # Manage Users' pager needs a real total_count across the whole
    # matching set, not just this page's row count — see
    # app/schemas/pagination.py's module docstring for why this endpoint
    # (and only this one plus the other two Manage Users tables use)
    # returns an envelope instead of the bare-array shape most list
    # endpoints use.
    total_count = (
        await db.execute(select(func.count()).select_from(User).where(*_LIST_USERS_FILTER))
    ).scalar_one()
    stmt = (
        select(User)
        .where(*_LIST_USERS_FILTER)
        .order_by(User.created_at.desc())
        .offset(pagination["offset"])
        .limit(pagination["page_size"])
    )
    result = await db.execute(stmt)
    return PaginatedResponse(
        data=list(result.scalars().all()),
        pagination=build_pagination_meta(
            page=pagination["page"],
            page_size=pagination["page_size"],
            offset=pagination["offset"],
            total_count=total_count,
        ),
    )


@router.get("/{user_id}", response_model=UserRead, dependencies=[require_privilege("user:manage")])
async def get_user(user_id: UUID, db: DbSession) -> User:
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("User not found")
    return user


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_privilege("user:manage")],
)
async def delete_user(user_id: UUID, current_user: CurrentUser, db: DbSession) -> None:
    """Removes the user from Manage Users entirely — matches the
    reference system's own trash-can action (its `dart_user.end_date`
    temporal column has the same effect: an end-dated row isn't in any
    "current" view). Not a "Deactivate" that keeps the row listed with a
    badge — that was this backend's own earlier, incorrect design; see
    User.deleted_at's docstring for why a soft-delete flag is still the
    right underlying mechanism even though the visible behavior is a
    real removal."""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("User not found")
    user.deleted_at = datetime.now(UTC)
    user.is_active = False
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="user.deleted",
        entity_type="user",
        entity_id=str(user.id),
    )
    await db.commit()


@router.patch(
    "/{user_id}/user-types",
    response_model=UserRead,
    dependencies=[require_privilege("user:manage")],
)
async def update_user_types(
    user_id: UUID, body: UserTypesUpdate, current_user: CurrentUser, db: DbSession
) -> User:
    """The reference system's "User Type" multi-select. Labels are synced
    to real grants via `sync_user_type_grants` — Account Admin is
    `is_superuser`; the security types get `security:manage`; Recon User
    can open recons linked to a group they belong to."""
    user = await db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFoundError("User not found")

    user.user_types = body.user_types
    await sync_user_type_grants(db, user)
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="user.types_updated",
        entity_type="user",
        entity_id=str(user.id),
        detail={"user_types": ", ".join(body.user_types) or "(none)"},
    )
    await db.commit()
    await db.refresh(user)
    return user
