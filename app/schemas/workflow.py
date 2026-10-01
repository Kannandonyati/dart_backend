"""Workflow request/response shapes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.workflow import WorkflowRunStatus, WorkflowRunStepStatus, WorkflowTriggerKind


class WorkflowStepDef(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    type: str = Field(min_length=1, max_length=80)
    ignore_kickout: bool = False
    kickout_tolerance: int = Field(default=0, ge=0, le=1_000_000)
    app_number: int | None = Field(default=None, ge=1, le=5)
    app_name: str = Field(default="", max_length=200)


class WorkflowDefinition(BaseModel):
    steps: list[WorkflowStepDef] = Field(min_length=1, max_length=20)
    on_success_emails: str = Field(default="", max_length=2000)
    on_failure_emails: str = Field(default="", max_length=2000)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    recon_id: uuid.UUID
    definition: WorkflowDefinition | None = None
    schedule_cron: str | None = Field(default=None, max_length=100)
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    is_paused: bool = False


class WorkflowUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    definition: WorkflowDefinition | None = None
    schedule_cron: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    is_paused: bool | None = None


class WorkflowRead(BaseModel):
    id: uuid.UUID
    name: str
    recon_id: uuid.UUID
    recon_name: str
    definition: dict[str, Any]
    schedule_cron: str | None
    timezone: str
    is_paused: bool
    next_run_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    latest_run: "WorkflowRunRead | None" = None


class WorkflowRunStepRead(BaseModel):
    id: uuid.UUID
    step_key: str
    step_type: str
    status: WorkflowRunStepStatus
    attempt: int
    detail: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None


class WorkflowRunRead(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    workflow_name: str
    recon_id: uuid.UUID
    status: WorkflowRunStatus
    trigger_kind: WorkflowTriggerKind
    triggered_by: str
    current_step: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    steps: list[WorkflowRunStepRead] = Field(default_factory=list)


WorkflowRead.model_rebuild()
