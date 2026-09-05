"""Sync Mapping request-response shapes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SyncMappingCreate(BaseModel):
    app_number: int = Field(ge=1, le=5)
    dimension_names: list[str] = Field(min_length=1)
    concat_delimiter: str = Field(default="-", min_length=1, max_length=5)
    source_sync: str = Field(min_length=1, max_length=1000)
    target_sync: str = Field(min_length=1, max_length=500)
    flip_sign: bool = False

    @field_validator("dimension_names")
    @classmethod
    def _no_blank_names(cls, v: list[str]) -> list[str]:
        cleaned = [d.strip() for d in v]
        if any(not d for d in cleaned):
            raise ValueError("dimension_names cannot contain blank entries")
        return cleaned


class SyncMappingUpdate(BaseModel):
    target_sync: str | None = Field(default=None, min_length=1, max_length=500)
    flip_sign: bool | None = None


class SyncMappingRead(BaseModel):
    id: uuid.UUID
    recon_id: uuid.UUID
    app_number: int
    dimension_names: list[str]
    concat_delimiter: str
    source_sync: str
    target_sync: str
    flip_sign: bool
    created_at: datetime
    updated_at: datetime


class SyncedRowRead(BaseModel):
    id: uuid.UUID
    app_number: int
    row_number: int
    data: dict[str, str]
    synced: dict[str, str]
