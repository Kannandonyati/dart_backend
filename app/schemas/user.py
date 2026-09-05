"""User request/response shapes.

UserRead deliberately never includes `hashed_password` — it isn't just
omitted by convention, the field doesn't exist on this schema at all,
so there's no field to accidentally serialize even if a future edit
passes the wrong object into a response_model.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import USER_TYPE_VALUES


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: EmailStr
    username: str
    is_active: bool
    user_types: list[str]
    created_at: datetime
    is_superuser: bool = False
    is_platform_admin: bool = False
    """Exposed so the frontend can decide what to render without probing
    endpoints for 403s. Read-only everywhere: neither flag appears on
    UserCreate or UserTypesUpdate, so surfacing them here cannot become
    a way to set them."""


class UserDirectoryEntry(BaseModel):
    id: uuid.UUID
    username: str
    user_types: list[str]


class UserTypesUpdate(BaseModel):
    user_types: list[str]

    @field_validator("user_types")
    @classmethod
    def _known_values_only(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(USER_TYPE_VALUES))
        if unknown:
            raise ValueError(f"Unknown user type(s): {', '.join(unknown)}")
        # De-duplicated, in USER_TYPE_VALUES' canonical order — same
        # reasoning as sync_mappings' dimension ordering: deterministic
        # output regardless of the order the caller submitted.
        return [t for t in USER_TYPE_VALUES if t in v]


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=150, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def _password_not_trivially_weak(cls, v: str) -> str:
        # Deliberately light-touch: length (enforced by Field above) does
        # more for real security than character-class rules, which mostly
        # train users to pick predictable substitutions. This only blocks
        # the degenerate cases a length check alone lets through.
        if v.isdigit() or v.isalpha():
            raise ValueError("Password must contain a mix of letters and digits/symbols.")
        return v

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.lower()
