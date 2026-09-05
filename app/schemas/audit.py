"""Audit log request/response shapes."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_username: str | None = None
    recon_id: uuid.UUID | None
    recon_name: str | None = None
    action: str
    entity_type: str | None
    entity_id: str | None
    detail: dict[str, str] | None
    created_at: datetime
