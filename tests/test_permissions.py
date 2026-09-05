"""Unit tests for app/core/permissions.py — the direct replacement for
the old backend's f_validate_access. Every case that query needs to
handle gets a test, per the module's own docstring promise."""

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_privilege
from app.models.user import User


async def test_user_without_any_membership_has_no_privilege(
    db_session: AsyncSession, make_user: Callable[..., Awaitable[User]]
) -> None:
    user = await make_user()
    assert await user_has_privilege(db_session, user.id, "user:manage") is False


async def test_user_with_granted_privilege_has_it(
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[User]],
    grant_privilege: Callable[..., Awaitable[None]],
) -> None:
    user = await make_user()
    await grant_privilege(user, "user:manage")
    assert await user_has_privilege(db_session, user.id, "user:manage") is True


async def test_user_does_not_have_a_different_privilege_than_the_one_granted(
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[User]],
    grant_privilege: Callable[..., Awaitable[None]],
) -> None:
    """Granting "user:manage" must not accidentally also grant
    "recon:delete" — this is the exact shape of bug that made a recon
    with zero group links deny *every* privilege check in the old
    backend; a privilege check has to be precise about which privilege
    it's checking, not just "does this user have some role"."""
    user = await make_user()
    await grant_privilege(user, "user:manage")
    assert await user_has_privilege(db_session, user.id, "recon:delete") is False


async def test_granting_privilege_to_one_user_does_not_leak_to_another(
    db_session: AsyncSession,
    make_user: Callable[..., Awaitable[User]],
    grant_privilege: Callable[..., Awaitable[None]],
) -> None:
    user_a = await make_user(email="a@dart.com", username="a")
    user_b = await make_user(email="b@dart.com", username="b")
    await grant_privilege(user_a, "user:manage")

    assert await user_has_privilege(db_session, user_a.id, "user:manage") is True
    assert await user_has_privilege(db_session, user_b.id, "user:manage") is False
