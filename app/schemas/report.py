"""Run Report request-response shapes."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class ReportRowRead(BaseModel):
    match_key: dict[str, str]
    app1_data: dict[str, str] | None
    app2_data: dict[str, str] | None
    app1_amount: Decimal
    app2_amount: Decimal
    variance: Decimal
    is_variance: bool


class ReportSummaryRead(BaseModel):
    baseline_app: int
    comparison_app: int
    variance_threshold: Decimal
    total_rows: int
    variance_count: int
    variance_percentage: float


class ReportRunResponse(BaseModel):
    rows: list[ReportRowRead]
    summary: ReportSummaryRead


class SignoffRequest(BaseModel):
    app_numbers: list[int] = Field(min_length=1)
    signed_off: bool

    @field_validator("app_numbers")
    @classmethod
    def _valid_app_numbers(cls, v: list[int]) -> list[int]:
        if any(n < 1 or n > 5 for n in v):
            raise ValueError("app_numbers must each be between 1 and 5")
        return v


class SignoffRead(BaseModel):
    app_number: int
    signed_off: bool
    signed_off_by_id: uuid.UUID | None
    signed_off_at: datetime | None


class LastRefreshRead(BaseModel):
    app_number: int
    last_refresh: datetime | None


class ReportFilterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    criteria: dict[str, list[str]] = Field(min_length=1)


class ReportFilterUpdate(BaseModel):
    criteria: dict[str, list[str]] = Field(min_length=1)


class ReportFilterRead(BaseModel):
    id: uuid.UUID
    recon_id: uuid.UUID
    name: str
    criteria: dict[str, list[str]]
    created_at: datetime
    updated_at: datetime
