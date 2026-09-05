"""Recon request/response shapes.

`ReconRead` is built manually in the endpoint, not via `from_attributes`
auto-mapping — `owner` (username) and `group_name` are derived from
relationships, not plain columns, so the endpoint constructs this
explicitly rather than relying on Pydantic to guess how to flatten them.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ReconCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ReconUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class ReconRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    group_name: str | None
    owner: str
    status: str
    archived: bool
    last_modified: datetime
