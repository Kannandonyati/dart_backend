from datetime import datetime

from pydantic import BaseModel


class AuditModeRead(BaseModel):
    enabled: bool
    admin_name: str | None = None
    start_date: datetime | None = None


class AuditModeUpdate(BaseModel):
    enabled: bool
