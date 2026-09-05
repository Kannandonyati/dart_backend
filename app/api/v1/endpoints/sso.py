"""SSO providers, OIDC exchange, and login-activity log.

Public list is AllowAny and never includes client_secret — same contract
as old Dart GET recon_security/sso/providers. Writes need security:manage.
"""

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.audit import record_audit_log
from app.core.audit_mode import current_audit_status
from app.core.exceptions import AppError, NotFoundError, UnauthorizedError
from app.core.oidc import exchange_authorization_code
from app.core.permissions import require_privilege
from app.core.rate_limit import limiter
from app.core.security import create_access_token, create_refresh_token
from app.core.system_log import record_system_log
from app.models.sso import SsoAuditLog, SsoProvider
from app.models.user import User
from app.schemas.common import Token
from app.schemas.sso import (
    SsoAuditLogRead,
    SsoExchangeRequest,
    SsoProviderManaged,
    SsoProviderPublic,
    SsoProviderUpsert,
)

router = APIRouter(prefix="/sso", tags=["sso"])
_MANAGE = require_privilege("security:manage")


def _public(row: SsoProvider) -> SsoProviderPublic:
    return SsoProviderPublic(
        provider_key=row.provider_key,
        display_name=row.display_name,
        client_id=row.client_id,
        discovery_url=row.discovery_url,
        extra_params=row.extra_params or {},
        is_enabled=row.is_enabled,
        logo_key=row.logo_key,
    )


def _managed(row: SsoProvider) -> SsoProviderManaged:
    return SsoProviderManaged(
        **_public(row).model_dump(),
        has_secret=bool(row.client_secret),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _write_sso_audit(
    db: DbSession,
    *,
    provider_key: str,
    email: str,
    username: str | None,
    success: bool,
    message: str,
) -> None:
    db.add(
        SsoAuditLog(
            provider_key=provider_key,
            email=email,
            username=username,
            success=success,
            message=message,
        )
    )
    await db.commit()


@router.get("/providers", response_model=list[SsoProviderPublic])
async def list_enabled_providers(db: DbSession) -> list[SsoProviderPublic]:
    stmt = (
        select(SsoProvider)
        .where(SsoProvider.is_enabled.is_(True))
        .order_by(SsoProvider.display_name)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_public(row) for row in rows]


@router.get("/providers/manage", response_model=list[SsoProviderManaged], dependencies=[_MANAGE])
async def list_managed_providers(db: DbSession) -> list[SsoProviderManaged]:
    stmt = select(SsoProvider).order_by(SsoProvider.display_name)
    rows = (await db.execute(stmt)).scalars().all()
    return [_managed(row) for row in rows]


@router.post("/providers", response_model=SsoProviderManaged, dependencies=[_MANAGE])
async def upsert_provider(
    body: SsoProviderUpsert, current_user: CurrentUser, db: DbSession
) -> SsoProviderManaged:
    stmt = select(SsoProvider).where(SsoProvider.provider_key == body.provider_key)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        if not body.client_secret:
            raise AppError("Client secret is required when adding a provider.")
        row = SsoProvider(
            provider_key=body.provider_key,
            display_name=body.display_name,
            client_id=body.client_id,
            client_secret=body.client_secret,
            discovery_url=body.discovery_url,
            extra_params=body.extra_params,
            logo_key=body.logo_key,
            is_enabled=body.is_enabled,
        )
        db.add(row)
        action = "sso.provider_created"
    else:
        row.display_name = body.display_name
        row.client_id = body.client_id
        row.discovery_url = body.discovery_url
        row.extra_params = body.extra_params
        row.logo_key = body.logo_key
        row.is_enabled = body.is_enabled
        if body.client_secret:
            row.client_secret = body.client_secret
        action = "sso.provider_updated"

    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action=action,
        entity_type="sso_provider",
        entity_id=body.provider_key,
        detail={"display_name": body.display_name},
    )
    await db.commit()
    await db.refresh(row)
    return _managed(row)


@router.post(
    "/providers/{provider_key}/toggle",
    response_model=SsoProviderManaged,
    dependencies=[_MANAGE],
)
async def toggle_provider(
    provider_key: str, current_user: CurrentUser, db: DbSession
) -> SsoProviderManaged:
    row = (
        await db.execute(select(SsoProvider).where(SsoProvider.provider_key == provider_key))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("SSO provider not found")
    row.is_enabled = not row.is_enabled
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="sso.provider_toggled",
        entity_type="sso_provider",
        entity_id=provider_key,
        detail={"is_enabled": row.is_enabled},
    )
    await db.commit()
    await db.refresh(row)
    return _managed(row)


@router.delete("/providers/{provider_key}", status_code=204, dependencies=[_MANAGE])
async def delete_provider(provider_key: str, current_user: CurrentUser, db: DbSession) -> None:
    row = (
        await db.execute(select(SsoProvider).where(SsoProvider.provider_key == provider_key))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("SSO provider not found")
    await record_audit_log(
        db,
        actor_user_id=current_user.id,
        action="sso.provider_deleted",
        entity_type="sso_provider",
        entity_id=provider_key,
        detail={"display_name": row.display_name},
    )
    await db.delete(row)
    await db.commit()


@router.post("/exchange", response_model=Token)
@limiter.limit("5/minute")
async def exchange_sso(request: Request, body: SsoExchangeRequest, db: DbSession) -> Token:
    row = (
        await db.execute(
            select(SsoProvider).where(
                SsoProvider.provider_key == body.provider_key,
                SsoProvider.is_enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError(
            f"Unknown or disabled SSO provider: {body.provider_key}",
            code="sso_provider_unknown",
        )

    email = "unknown"
    try:
        identity = await exchange_authorization_code(
            client_id=row.client_id,
            client_secret=row.client_secret,
            discovery_url=row.discovery_url,
            code=body.code,
            code_verifier=body.code_verifier,
            redirect_uri=body.redirect_uri,
        )
        email = identity.email
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None or not user.is_active:
            await _write_sso_audit(
                db,
                provider_key=body.provider_key,
                email=email,
                username=None,
                success=False,
                message="No active DART user for this identity",
            )
            raise UnauthorizedError("Invalid email or password", code="invalid_credentials")

        await record_audit_log(
            db,
            actor_user_id=user.id,
            action="auth.sso_login",
            entity_type="user",
            entity_id=str(user.id),
            detail={"provider_key": body.provider_key},
        )
        await _write_sso_audit(
            db,
            provider_key=body.provider_key,
            email=email,
            username=user.username,
            success=True,
            message="SSO login",
        )
        request_id = getattr(request.state, "request_id", None)
        await record_system_log(
            log_name="userlog",
            logging_level="INFO",
            log_message=f"{user.username} authenticated via SSO ({body.provider_key})",
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
    except (UnauthorizedError, AppError):
        raise
    except Exception:
        await _write_sso_audit(
            db,
            provider_key=body.provider_key,
            email=email,
            username=None,
            success=False,
            message="SSO exchange failed",
        )
        raise


@router.get("/audit-logs", response_model=list[SsoAuditLogRead], dependencies=[_MANAGE])
async def list_sso_audit_logs(db: DbSession) -> list[SsoAuditLogRead]:
    stmt = select(SsoAuditLog).order_by(SsoAuditLog.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return [
        SsoAuditLogRead(
            provider_key=row.provider_key,
            email=row.email,
            username=row.username,
            success=row.success,
            message=row.message,
            created_at=row.created_at,
        )
        for row in rows
    ]
