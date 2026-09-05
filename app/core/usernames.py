"""Shared username derivation — one email-local-part-to-username rule,
used everywhere a username isn't explicitly supplied.

Matches the old backend's own convention exactly: `manage_users/views.py`'s
`user_invite` view does `username = email.split('@')[0]` before ever
touching the database. Originally written for `app/db/seed.py` (to fix a
real bug: hardcoded literal usernames colliding with a pre-existing row),
then reused here once Phase 9's `POST /users/invite` needed the same
derivation — the reference frontend's invite form only collects an email,
never a username, so the backend deriving one is required for that form
to work at all, not just a nicety.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


async def derive_unique_username(db: AsyncSession, email: str) -> str:
    """Falls back to `<local>2`, `<local>3`, ... on an actual collision,
    same as a human would when told a username is taken."""
    base = re.sub(r"[^a-zA-Z0-9_.-]", "_", email.split("@", 1)[0]) or "user"
    candidate = base
    suffix = 2
    while (
        await db.execute(select(User.id).where(User.username == candidate))
    ).scalar_one_or_none() is not None:
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate
