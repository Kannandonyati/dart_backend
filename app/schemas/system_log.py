"""Maintenance system-log read shape — old Dart UNION columns."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SystemLogRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    log_name: str
    logging_level: str
    log_message: str
    request_url: str | None
    request_id: str | None
    username: str | None
    user_email: str | None
    recon_name: str | None
    event_stage: str | None
    time_taken: str | None
    variable_state: dict[str, Any] | None
    actor_user_id: uuid.UUID | None
    recon_id: uuid.UUID | None
    created_at: datetime
