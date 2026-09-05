"""Async SQLAlchemy engine, session factory, and the `get_db` dependency.

Every query in this codebase goes through SQLAlchemy's parameterized
query construction — never raw string-formatted SQL. That's not a style
preference; it's the direct fix for the class of bug this project has
already lived through on the DB-driven side, where business logic (and
its bugs) lived in a stored procedure nobody could read, test, or safely
change. Here, a query is Python, is reviewable, and is unit-testable.

Pool sizing (database_pool_size / database_max_overflow, from Settings)
is deliberately explicit rather than left at SQLAlchemy's defaults —
at ~30 lakh-record import/report workloads you will have async API
workers, Celery workers, and Airflow-triggered jobs all opening
connections concurrently; an unbounded or too-small pool is how that
turns into "FATAL: too many connections" under load instead of a
predictable, tunable ceiling.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.cache.redis import resolve_loopback_url
from app.core.config import settings

engine: AsyncEngine = create_async_engine(
    resolve_loopback_url(str(settings.database_url)),
    echo=settings.database_echo,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,  # detects a dead connection before handing it to a request
    connect_args={"timeout": 5},
)

async_session_factory = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency: one session per request, always closed, rolled
    back on any exception so a failed request can never leave a
    half-committed transaction sitting on a pooled connection."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession]:
    """Same contract as get_db, for use outside a request in a process
    that only ever runs one asyncio event loop for its whole lifetime —
    startup scripts, one-off maintenance code. **Not safe for Celery
    tasks** — see `celery_session_scope` below for why."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def celery_session_scope() -> AsyncGenerator[AsyncSession]:
    """Same contract as `session_scope`, but safe for Celery tasks
    specifically. A Celery task (this codebase's pattern: a sync
    function wrapping `asyncio.run(...)`) gets a brand-new event loop on
    every single invocation, for the life of a long-running worker
    process — but the module-level `engine` above is a singleton whose
    pooled asyncpg connections are bound to whichever event loop was
    running when they were first opened. Reusing `engine`/
    `async_session_factory` from a second task invocation (a second,
    different event loop) raises `RuntimeError: Future ... attached to a
    different loop` — hit for real during Phase 5's Run Import task
    development, the same class of bug Phase 1's KT documents for
    pytest-asyncio (see that KT's "Windows + asyncpg + pytest-asyncio
    event-loop mismatch" entry) but with no equivalent of pytest's
    session-scoped-loop fixture available inside a worker process.

    The fix here: a dedicated engine, created fresh inside the task's
    own event loop and disposed before returning, so no connection ever
    outlives the loop it was opened on."""
    task_engine = create_async_engine(
        resolve_loopback_url(str(settings.database_url)),
        pool_pre_ping=True,
        connect_args={"timeout": 5},
    )
    task_session_factory = async_sessionmaker(
        bind=task_engine, expire_on_commit=False, autoflush=False
    )
    try:
        async with task_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()
    finally:
        await task_engine.dispose()


async def check_db_connection() -> bool:
    """Used by the /health/db check — cheap, no side effects."""
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True
