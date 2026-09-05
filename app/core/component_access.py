"""Resolving stored overrides into "what may this user actually see".

Three rules, in order:

1. A platform admin sees everything. Non-negotiable — it's what makes
   every switch in the console safe to flip, because there is no
   combination of settings that can lock the tier that manages them out
   of the application.
2. A component is visible unless something says otherwise. Absence of a
   row means stock behavior, and an override whose key has dropped out of
   the catalog is ignored rather than obeyed.
3. The most specific override wins: a row naming one of the user's own
   user types beats the `everyone` baseline. Where a user holds several
   types with conflicting rows, *enabled* wins — a user who is both an
   Account Admin and a Recon User keeps what either type grants, so
   narrowing one type can never quietly remove access the other confers.

A disabled parent hides its whole subtree (`ancestors_of`), so the
console needs one switch for "the Workflow Automation group" instead of
asking an operator to remember all six children.
"""

import uuid
from collections.abc import Iterable
from typing import cast

from fastapi import Depends
from fastapi.params import Depends as DependsMarker
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DbSession
from app.core.exceptions import PermissionDeniedError
from app.core.ui_components import (
    ALL_COMPONENTS,
    COMPONENTS_BY_KEY,
    ancestors_of,
    components_for_api_path,
)
from app.models.ui_component import EVERYONE_AUDIENCE, UiComponentSetting
from app.models.user import User


async def load_settings(db: AsyncSession) -> list[UiComponentSetting]:
    return list((await db.execute(select(UiComponentSetting))).scalars().all())


def _own_enabled_state(
    settings: Iterable[UiComponentSetting], key: str, user_types: Iterable[str]
) -> bool:
    """Whether this one component is switched on for this user, ignoring
    its ancestors."""
    types = set(user_types)
    rows = [s for s in settings if s.component_key == key]

    specific = [s for s in rows if s.audience in types]
    if specific:
        # Enabled wins across the user's own types — see rule 3.
        return any(s.is_enabled for s in specific)

    for row in rows:
        if row.audience == EVERYONE_AUDIENCE:
            return row.is_enabled
    return True


def is_component_visible(
    settings: Iterable[UiComponentSetting],
    key: str,
    *,
    user: User,
) -> bool:
    if user.is_platform_admin:
        return True
    component = COMPONENTS_BY_KEY.get(key)
    if component is None:
        # Unknown key — nothing in the catalog claims it, so there is
        # nothing to hide. Fail open rather than blocking a route the
        # catalog simply hasn't caught up with.
        return True
    if component.platform_only or any(
        (COMPONENTS_BY_KEY.get(ancestor) is not None)
        and COMPONENTS_BY_KEY[ancestor].platform_only
        for ancestor in ancestors_of(key)
    ):
        return False
    if component.locked:
        return True

    settings = list(settings)
    if not _own_enabled_state(settings, key, user.user_types):
        return False
    return all(
        _own_enabled_state(settings, ancestor, user.user_types)
        or COMPONENTS_BY_KEY.get(ancestor, component).locked
        for ancestor in ancestors_of(key)
    )


def visible_component_keys(settings: Iterable[UiComponentSetting], *, user: User) -> list[str]:
    """Every catalog key this user may see, for the frontend to filter
    its navigation and tabs against. Sent as the allow-list rather than
    the deny-list so a frontend that predates a new component shows it
    (it isn't in the list, so nothing references it) instead of a
    frontend that postdates one hiding it."""
    settings = list(settings)
    return [c.key for c in ALL_COMPONENTS if is_component_visible(settings, c.key, user=user)]


async def assert_api_path_enabled(db: AsyncSession, user: User, path: str) -> None:
    """Raises 403 if any component owning this path is switched off for
    this user. Called from the guard dependency below, and kept separate
    so it's directly unit-testable without a request."""
    owners = components_for_api_path(path)
    if not owners:
        return
    settings = await load_settings(db)
    for component in owners:
        if not is_component_visible(settings, component.key, user=user):
            raise PermissionDeniedError(
                f"{component.label} has been disabled by your administrator.",
                code="component_disabled",
            )


def require_component_enabled(key: str) -> DependsMarker:
    """Route-level guard for a component that owns an endpoint but whose
    path the catalog can't claim by prefix (or where being explicit at
    the route reads better than relying on the prefix table)."""

    async def _check(current_user: CurrentUser, db: DbSession) -> None:
        settings = await load_settings(db)
        if not is_component_visible(settings, key, user=current_user):
            component = COMPONENTS_BY_KEY.get(key)
            label = component.label if component else key
            raise PermissionDeniedError(
                f"{label} has been disabled by your administrator.",
                code="component_disabled",
            )

    return cast(DependsMarker, Depends(_check))


async def user_visible_keys(db: AsyncSession, user_id: uuid.UUID) -> list[str]:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    return visible_component_keys(await load_settings(db), user=user)
