"""Workflow definitions and durable run history.

Replaces old DART Airflow (generated .py DAGs + HTTP into Django) with
rows in this database. Celery executes the steps in-process against the
existing import/bridge/transform/report services — see
app/tasks/workflow_tasks.py.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.recon import Recon
    from app.models.user import User


class WorkflowRunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowRunStepStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowTriggerKind(enum.StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        Index(
            "uq_workflows_name_live",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_workflows_recon_id", "recon_id"),
        Index("ix_workflows_next_run_at", "next_run_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    recon_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recons.id", ondelete="CASCADE"), nullable=False
    )
    definition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(100), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="UTC")
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    recon: Mapped["Recon"] = relationship()
    created_by: Mapped["User"] = relationship()
    runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="workflow")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index(
            "uq_workflow_runs_active",
            "workflow_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        Index("ix_workflow_runs_workflow_id", "workflow_id"),
        Index("ix_workflow_runs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[WorkflowRunStatus] = mapped_column(
        String(20), nullable=False, default=WorkflowRunStatus.QUEUED
    )
    trigger_kind: Mapped[WorkflowTriggerKind] = mapped_column(
        String(20), nullable=False, default=WorkflowTriggerKind.MANUAL
    )
    triggered_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    current_step: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    workflow: Mapped[Workflow] = relationship(back_populates="runs")
    triggered_by: Mapped["User"] = relationship()
    steps: Mapped[list["WorkflowRunStep"]] = relationship(back_populates="run")


class WorkflowRunStep(Base):
    __tablename__ = "workflow_run_steps"
    __table_args__ = (Index("ix_workflow_run_steps_run_id", "run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False
    )
    step_key: Mapped[str] = mapped_column(String(80), nullable=False)
    step_type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[WorkflowRunStepStatus] = mapped_column(
        String(20), nullable=False, default=WorkflowRunStepStatus.PENDING
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[WorkflowRun] = relationship(back_populates="steps")
