"""Current open audit-mode row — used by login and the Manage Security toggle."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_mode import AuditMode


async def current_audit_mode(db: AsyncSession) -> AuditMode | None:
    stmt = (
        select(AuditMode)
        .where(AuditMode.end_date.is_(None))
        .order_by(AuditMode.start_date.desc())
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def current_audit_status(db: AsyncSession) -> bool:
    row = await current_audit_mode(db)
    return bool(row and row.audit_status)
