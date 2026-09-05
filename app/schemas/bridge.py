"""Bridge Mapping / Bridge Run request-response shapes.

Fields match old `vw_recon_bridge_mapping` plus the FastAPI ids:
Recon App, Dimension, Source Member, Bridge Member, Flip Sign,
Dimension Comment, Journal Entry Comment, Bridge Comment, Invalid Flag.
Kickouts match old `kickout_list.py` (`Common_dimension_name`,
`Source_member`, `app_type`, `app_name`, `Bridge_member`).
Bridged data adds `amount` / `sign_reversed_amount` from
`f_create_bridge_table`'s product of per-dimension `flip_sign`.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.bridge import BridgeRunStatus


class BridgeMappingCreate(BaseModel):
    app_number: int = Field(ge=1, le=5)
    dimension_name: str = Field(min_length=1, max_length=200)
    source_member: str = Field(min_length=1, max_length=500)
    bridge_member: str = Field(min_length=1, max_length=500)
    flip_sign: bool = False
    dim_comment: str | None = Field(default=None, max_length=1000)
    bridge_comment: str | None = Field(default=None, max_length=1000)
    je_comment: str | None = Field(default=None, max_length=1000)
    is_invalid: bool = False


class BridgeMappingUpdate(BaseModel):
    source_member: str | None = Field(default=None, min_length=1, max_length=500)
    bridge_member: str | None = Field(default=None, min_length=1, max_length=500)
    flip_sign: bool | None = None
    dim_comment: str | None = Field(default=None, max_length=1000)
    bridge_comment: str | None = Field(default=None, max_length=1000)
    je_comment: str | None = Field(default=None, max_length=1000)
    is_invalid: bool | None = None


class BridgeMappingRead(BaseModel):
    id: uuid.UUID
    recon_id: uuid.UUID
    app_number: int
    app_name: str | None
    app_type: str
    dimension_name: str
    source_member: str
    bridge_member: str
    is_kickout: bool
    flip_sign: bool
    dim_comment: str | None
    bridge_comment: str | None
    je_comment: str | None
    is_invalid: bool
    created_at: datetime
    updated_at: datetime


class BridgeKickoutRead(BaseModel):
    app_number: int
    app_name: str | None
    app_type: str
    dimension_name: str
    source_member: str
    bridge_member: str
    Common_dimension_name: str
    Source_member: str
    Bridge_member: str


class BridgeKickoutResolve(BaseModel):
    app_number: int = Field(ge=1, le=5)
    dimension_name: str = Field(min_length=1, max_length=200)
    source_member: str = Field(min_length=1, max_length=500)
    bridge_member: str = Field(min_length=1, max_length=500)
    flip_sign: bool = False
    dim_comment: str | None = Field(default=None, max_length=1000)
    bridge_comment: str | None = Field(default=None, max_length=1000)
    je_comment: str | None = Field(default=None, max_length=1000)


class BridgeRunRead(BaseModel):
    id: uuid.UUID
    recon_id: uuid.UUID
    status: BridgeRunStatus
    total_rows: int | None
    processed_rows: int
    kickout_count: int | None
    error_message: str | None
    created_by: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BridgeDataRowRead(BaseModel):
    id: uuid.UUID
    app_number: int
    app_name: str | None
    app_type: str
    row_number: int
    data: dict[str, str]
    resolved: dict[str, str]
    kickout: bool
    amount: str
    sign_reversed_amount: str
    user_comment: str
    je_comment: str
