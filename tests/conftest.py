"""Shared test fixtures.

Tests run against a real, dedicated `dart_test` Postgres database (same
`dart` role, separate database from the `dart` dev database) — not
mocks, not SQLite. `app.db.session`'s engine/session-factory already
point at whatever DATABASE_URL is in the environment when the app
module is first imported, and that's set to dart_test below *before*
any app import happens in this file — so the app's real `get_db`
dependency naturally talks to the test database with zero dependency
overrides needed.

Isolation between tests is TRUNCATE-based, not transaction-rollback: a
session-scoped fixture creates every table once, and a function-scoped
autouse fixture truncates them all after each test. This is simpler than
the SAVEPOINT-based rollback pattern async SQLAlchemy testing usually
needs (endpoints call `db.commit()` themselves, e.g.
app/api/v1/endpoints/users.py, which would prematurely release a naive
outer transaction) — correct and fast enough for this test suite's size.
"""

import os
import uuid as uuid_module
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Test-only settings, force-set (not setdefault) so a value already
# present in the host machine's environment — e.g. a stray ALLOWED_HOSTS
# some other local tool set — can never silently leak into the test run
# and produce a result that depends on whose machine CI happens to be on.
# Must run before app.core.config.settings (and therefore app.db.session)
# is first imported anywhere, since Settings is cached with @lru_cache.
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-characters-long"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://dart:D%40art_Dony%40ti@localhost:5432/dart_test"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/15"
os.environ["CELERY_BROKER_URL"] = "redis://127.0.0.1:6379/14"
os.environ["CELERY_RESULT_BACKEND"] = "redis://127.0.0.1:6379/13"
# httpx's ASGITransport test client sends Host: test (from base_url below) —
# TrustedHostMiddleware correctly rejects that unless it's allow-listed here.
os.environ["ALLOWED_HOSTS"] = "test,localhost,127.0.0.1"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"

import app.models as _models  # noqa: E402, F401
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import async_session_factory, engine  # noqa: E402
from app.models.security import Membership, Privilege, Role, ScopeType  # noqa: E402
from app.models.user import User  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def _create_schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        # Drop first so a model-level constraint change (e.g. the live-only
        # unique index on recons.name) is actually applied. create_all
        # alone leaves an existing table's old unique constraint in place.
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _truncate_tables() -> AsyncIterator[None]:
    yield
    async with engine.begin() as conn:
        table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        if table_names:
            await conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


@pytest.fixture
def make_user(db_session: AsyncSession) -> Callable[..., Awaitable[User]]:
    """Factory fixture: `await make_user(email=..., password=..., is_superuser=...)`
    creates and commits a real user row, returning the ORM object."""

    async def _make(
        *,
        email: str = "user@dart.com",
        username: str = "testuser",
        password: str = "TestPassword123!",
        is_superuser: bool = False,
        is_platform_admin: bool = False,
        is_active: bool = True,
    ) -> User:
        user = User(
            email=email,
            username=username,
            hashed_password=hash_password(password),
            is_superuser=is_superuser,
            is_platform_admin=is_platform_admin,
            is_active=is_active,
            # Matches every direct-creation code path (POST /users, seed.py):
            # only the invite flow leaves this NULL. `is_active=False` here
            # models a deliberately-deactivated test user, not a pending
            # invite, so it still gets a real acceptance timestamp.
            invite_accepted_at=datetime.now(UTC),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _make


@pytest.fixture
def grant_privilege(db_session: AsyncSession) -> Callable[..., Awaitable[None]]:
    """Factory fixture: `await grant_privilege(user, "user:manage")` creates
    the Privilege/Role/Membership chain needed for a require_privilege()
    check to pass for that user, in a throwaway scope (the scope itself
    doesn't matter for Phase 1's coarse "has this privilege anywhere"
    check — see app/core/permissions.py)."""

    async def _grant(
        user: User,
        privilege_name: str,
        *,
        scope_type: ScopeType = ScopeType.LOB,
        scope_id: uuid_module.UUID | None = None,
    ) -> None:
        privilege = Privilege(name=privilege_name)
        role = Role(name=f"role-for-{privilege_name}-{uuid_module.uuid4()}", privileges=[privilege])
        membership = Membership(
            user_id=user.id,
            scope_type=scope_type,
            scope_id=scope_id or uuid_module.uuid4(),
            role=role,
        )
        db_session.add_all([privilege, role, membership])
        await db_session.commit()

    return _grant


@pytest.fixture
async def admin_role(db_session: AsyncSession) -> Role:
    """Creates the label-only "Admin" role that app/db/seed.py normally
    seeds in real environments (see app/api/v1/endpoints/lobs.py's
    ADMIN_ROLE_NAME) — tests run against a schema-only database with no
    seed data, so anything exercising the admin-membership endpoints
    needs this row to exist first."""
    role = Role(name="Admin")
    db_session.add(role)
    await db_session.commit()
    await db_session.refresh(role)
    return role
