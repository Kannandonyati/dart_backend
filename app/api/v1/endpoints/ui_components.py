"""The platform admin's UI component console, plus the read-only
visibility feed every client uses to filter its own navigation.

Two audiences, two access levels:

- `GET /ui-components/visibility` is for the running application. Any
  authenticated user may call it, and it only ever describes that
  caller — there's no way to ask what someone else can see.
- everything else is the console, and requires `is_platform_admin`.
  Not `security:manage` and not `is_superuser`: both of those are held
  by ordinary Account Admins (see app/models/user.py), who must not be
  able to reshape the application for the tenant that appointed them.
"""

from datetime import UTC, datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from fastapi.params import Depends as DependsMarker
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.core.audit import record_audit_log
from app.core.component_access import (
    assert_api_path_enabled,
    load_settings,
    visible_component_keys,
)
from app.core.config import settings as app_settings
from app.core.exceptions import AppError, NotFoundError, PermissionDeniedError
from app.core.ui_components import ALL_COMPONENTS, COMPONENTS_BY_KEY
from app.models.ui_component import EVERYONE_AUDIENCE, UiComponentSetting
from app.models.user import User
from app.schemas.ui_component import (
    AUDIENCE_VALUES,
    AudienceState,
    ComponentCatalog,
    ComponentEntry,
    ComponentSettingReset,
    ComponentSettingUpdate,
    ComponentVisibility,
)

router = APIRouter(prefix="/ui-components", tags=["platform"])


async def _require_platform_admin(current_user: CurrentUser) -> User:
    if not current_user.is_platform_admin:
        # 403 rather than 404: unlike a recon, this endpoint's existence
        # isn't a secret worth protecting (it's in the OpenAPI schema
        # either way), and a clear denial beats a misleading "no such
        # thing" for an operator debugging their own access.
        raise PermissionDeniedError(
            "This area is restricted to the platform administrator.",
            code="platform_admin_required",
        )
    return current_user


PlatformAdmin = Annotated[User, Depends(_require_platform_admin)]


async def _enforce_request_component(
    request: Request, current_user: OptionalUser, db: DbSession
) -> None:
    """Applied to the routers whose pages can be switched off, so a
    disabled component closes its API too. Derives the component from
    the request path via the catalog's `api_prefixes`, which keeps the
    key in one place instead of repeating it at every router.

    Unauthenticated callers are left alone: this guard must not invent
    an auth requirement the route itself doesn't have. Public
    token-redemption endpoints (`/users/accept-invite`,
    `/users/reset-password`) live under a guarded prefix and would 401
    if this demanded `CurrentUser`."""
    if current_user is None:
        return
    path = request.url.path
    prefix = app_settings.api_v1_prefix
    if path.startswith(prefix):
        path = path[len(prefix) :]
    await assert_api_path_enabled(db, current_user, path)


COMPONENT_GUARD = cast(DependsMarker, Depends(_enforce_request_component))


@router.get("/visibility", response_model=ComponentVisibility)
async def get_my_visibility(current_user: CurrentUser, db: DbSession) -> ComponentVisibility:
    return ComponentVisibility(
        visible_keys=visible_component_keys(await load_settings(db), user=current_user),
        is_platform_admin=current_user.is_platform_admin,
    )


@router.get("", response_model=ComponentCatalog)
async def list_components(_admin: PlatformAdmin, db: DbSession) -> ComponentCatalog:
    stmt = select(UiComponentSetting).options(selectinload(UiComponentSetting.updated_by))
    rows = list((await db.execute(stmt)).scalars().all())

    entries: list[ComponentEntry] = []
    for component in ALL_COMPONENTS:
        mine = [r for r in rows if r.component_key == component.key]
        baseline = next((r for r in mine if r.audience == EVERYONE_AUDIENCE), None)
        entries.append(
            ComponentEntry(
                key=component.key,
                label=component.label,
                kind=str(component.kind),
                parent=component.parent,
                description=component.description,
                locked=component.locked,
                platform_only=component.platform_only,
                api_prefixes=list(component.api_prefixes),
                enabled_for_everyone=baseline.is_enabled if baseline else True,
                overrides=[
                    AudienceState(
                        audience=r.audience,
                        is_enabled=r.is_enabled,
                        updated_by=r.updated_by.username if r.updated_by else None,
                        updated_at=r.updated_at,
                    )
                    for r in mine
                    if r.audience != EVERYONE_AUDIENCE
                ],
            )
        )
    return ComponentCatalog(components=entries, audiences=list(AUDIENCE_VALUES))


@router.put("/{component_key}", response_model=ComponentCatalog)
async def set_component(
    component_key: str,
    body: ComponentSettingUpdate,
    admin: PlatformAdmin,
    db: DbSession,
) -> ComponentCatalog:
    component = COMPONENTS_BY_KEY.get(component_key)
    if component is None:
        raise NotFoundError(f"Unknown UI component: {component_key}")
    if component.locked and not body.is_enabled:
        raise AppError(
            f"{component.label} cannot be disabled — the application would be "
            "unrecoverable without it.",
            code="component_locked",
        )

    existing = (
        await db.execute(
            select(UiComponentSetting).where(
                UiComponentSetting.component_key == component_key,
                UiComponentSetting.audience == body.audience,
            )
        )
    ).scalar_one_or_none()

    if existing is None:
        db.add(
            UiComponentSetting(
                component_key=component_key,
                audience=body.audience,
                is_enabled=body.is_enabled,
                updated_by_user_id=admin.id,
            )
        )
    else:
        existing.is_enabled = body.is_enabled
        existing.updated_by_user_id = admin.id
        existing.updated_at = datetime.now(UTC)

    await record_audit_log(
        db,
        actor_user_id=admin.id,
        action="ui_component.updated",
        entity_type="ui_component",
        entity_id=component_key,
        detail={"audience": body.audience, "enabled": str(body.is_enabled)},
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        # Two admins flipping the same switch at once — the unique
        # constraint on (component_key, audience) is what actually
        # guarantees one row, the SELECT above only avoids the common case.
        await db.rollback()
        raise AppError(
            "That switch was changed by someone else at the same time. Try again.",
            code="concurrent_update",
        ) from exc

    return await list_components(admin, db)


@router.post("/{component_key}/reset", response_model=ComponentCatalog)
async def reset_component(
    component_key: str,
    body: ComponentSettingReset,
    admin: PlatformAdmin,
    db: DbSession,
) -> ComponentCatalog:
    """Deletes the stored decision, returning the component to stock
    (visible). Distinct from setting it enabled: no row means "never
    decided", which is what the console shows as untouched."""
    if component_key not in COMPONENTS_BY_KEY:
        raise NotFoundError(f"Unknown UI component: {component_key}")

    existing = (
        await db.execute(
            select(UiComponentSetting).where(
                UiComponentSetting.component_key == component_key,
                UiComponentSetting.audience == body.audience,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        await db.delete(existing)
        await record_audit_log(
            db,
            actor_user_id=admin.id,
            action="ui_component.reset",
            entity_type="ui_component",
            entity_id=component_key,
            detail={"audience": body.audience},
        )
        await db.commit()

    return await list_components(admin, db)
