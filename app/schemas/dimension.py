"""Recon App and Dimension request/response shapes.

`DimensionMappingIn`'s validator (unique app numbers, must include
apps 1 and 2, extras 3–5 allowed; `in_file` implying `column_location`
and its absence implying `default_value`) enforces at the schema layer
what the old backend left to convention.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.recon_limits import MAX_RECON_APPS


class ReconAppCreate(BaseModel):
    app_number: int = Field(ge=1, le=MAX_RECON_APPS)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    delimiter: str = Field(default=",", min_length=1, max_length=5)
    currency_delimiter: str | None = Field(default=None, max_length=5)
    currency_symbol: str | None = Field(default=None, max_length=5)
    thousands_separator: str = Field(default=",", min_length=1, max_length=5)
    has_header: bool = True


class ReconAppUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    delimiter: str | None = Field(default=None, min_length=1, max_length=5)
    currency_delimiter: str | None = None
    currency_symbol: str | None = None
    thousands_separator: str | None = Field(default=None, min_length=1, max_length=5)
    has_header: bool | None = None


class ReconAppRead(BaseModel):
    id: uuid.UUID
    recon_id: uuid.UUID
    app_number: int
    name: str
    description: str | None
    delimiter: str
    currency_delimiter: str | None
    currency_symbol: str | None
    thousands_separator: str
    has_header: bool
    created_at: datetime
    updated_at: datetime


class DimensionMappingIn(BaseModel):
    app_number: int = Field(ge=1, le=MAX_RECON_APPS)
    in_file: bool
    column_location: str | None = Field(default=None, max_length=200)
    default_value: str | None = Field(default=None, max_length=500)
    is_active: bool = True

    @model_validator(mode="after")
    def _column_or_default(self) -> "DimensionMappingIn":
        if self.in_file and not self.column_location:
            raise ValueError("column_location is required when in_file is true")
        if not self.in_file and self.default_value is None:
            raise ValueError("default_value is required when in_file is false")
        return self


class DimensionMappingRead(BaseModel):
    app_number: int
    in_file: bool
    column_location: str | None
    default_value: str | None
    is_active: bool


def _validate_mapping_pair(mappings: list[DimensionMappingIn]) -> list[DimensionMappingIn]:
    app_numbers = [m.app_number for m in mappings]
    if len(app_numbers) != len(set(app_numbers)):
        raise ValueError("mappings must not repeat an app_number")
    if 1 not in app_numbers or 2 not in app_numbers:
        raise ValueError("mappings must include app_number 1 and 2")
    return mappings


class DimensionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    mappings: list[DimensionMappingIn]

    @field_validator("name")
    @classmethod
    def _uppercase_name(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("mappings")
    @classmethod
    def _mapping_pair(cls, v: list[DimensionMappingIn]) -> list[DimensionMappingIn]:
        return _validate_mapping_pair(v)


class DimensionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    mappings: list[DimensionMappingIn] | None = None

    @field_validator("name")
    @classmethod
    def _uppercase_name(cls, v: str | None) -> str | None:
        return v.strip().upper() if v else v

    @field_validator("mappings")
    @classmethod
    def _mapping_pair(cls, v: list[DimensionMappingIn] | None) -> list[DimensionMappingIn] | None:
        return _validate_mapping_pair(v) if v is not None else v


class DimensionRead(BaseModel):
    id: uuid.UUID
    recon_id: uuid.UUID
    name: str
    position: int
    is_mandatory: bool
    mappings: list[DimensionMappingRead]


class DimensionReorder(BaseModel):
    new_position: int = Field(ge=0)
