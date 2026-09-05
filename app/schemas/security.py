"""Lob/Team/Group/Role request-response shapes.

`*Read` schemas are built manually in the endpoints, not via
`from_attributes`, for the same reason as `ReconRead` (app/schemas/
recon.py): fields like `created_by`, `admins`, `members`, `lob_names`
are derived from relationships, not plain columns.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class LobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class LobUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class LobRead(BaseModel):
    id: uuid.UUID
    name: str
    created_by: str | None
    created_at: datetime


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lob_id: uuid.UUID


class TeamUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TeamRead(BaseModel):
    id: uuid.UUID
    name: str
    lob_id: uuid.UUID
    lob_name: str
    created_at: datetime


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class GroupUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class GroupRead(BaseModel):
    id: uuid.UUID
    name: str
    created_by: str | None
    created_at: datetime


class GroupDetails(BaseModel):
    id: uuid.UUID
    name: str
    admin_names: list[str]
    member_names: list[str]
    lob_names: list[str]
    team_names: list[str]
    role_names: list[str]
    recon_names: list[str]
    gv_names: list[str]


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    privilege_names: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    privilege_names: list[str] | None = None


class RoleRead(BaseModel):
    id: uuid.UUID
    name: str
    privileges: list[str]


class MembershipUserRef(BaseModel):
    """Add/remove a membership by user id — the frontend's old-backend
    contract keys by username, but every internal identity in this
    rebuild is UUID-first (same reasoning as ReconRead using id, not
    name, in Phase 2)."""

    user_id: uuid.UUID
