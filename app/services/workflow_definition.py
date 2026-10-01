"""Allowed workflow step types and default recon pipeline."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.dimension import ReconApp
from app.schemas.workflow import WorkflowDefinition, WorkflowStepDef

ALLOWED_STEP_TYPES = frozenset(
    {
        "import_app_data",
        "import_bridge_data",
        "upload_dimensions",
        "run_bridge",
        "check_kickouts",
        "run_transformation",
        "run_report",
    }
)

PIPELINE_TAIL = [
    WorkflowStepDef(key="run_bridge", type="run_bridge"),
    WorkflowStepDef(key="check_kickouts", type="check_kickouts"),
    WorkflowStepDef(key="run_transformation", type="run_transformation"),
    WorkflowStepDef(key="run_report", type="run_report"),
]

DEFAULT_DEFINITION = WorkflowDefinition(
    steps=[
        WorkflowStepDef(
            key="import_app_data_1",
            type="import_app_data",
            app_number=1,
            app_name="App 1",
        ),
        WorkflowStepDef(
            key="import_app_data_2",
            type="import_app_data",
            app_number=2,
            app_name="App 2",
        ),
        *PIPELINE_TAIL,
    ]
)


def pipeline_for_apps(apps: list[ReconApp]) -> WorkflowDefinition:
    imports = [
        WorkflowStepDef(
            key=f"import_app_data_{app.app_number}",
            type="import_app_data",
            app_number=app.app_number,
            app_name=app.name,
        )
        for app in sorted(apps, key=lambda row: row.app_number)
    ]
    if not imports:
        imports = list(DEFAULT_DEFINITION.steps[:2])
    return WorkflowDefinition(steps=[*imports, *PIPELINE_TAIL])


async def definition_for_recon(db: AsyncSession, recon_id: uuid.UUID) -> dict[str, Any]:
    apps = list(
        (
            await db.execute(
                select(ReconApp)
                .where(ReconApp.recon_id == recon_id)
                .order_by(ReconApp.app_number)
            )
        )
        .scalars()
        .all()
    )
    return validated_definition(pipeline_for_apps(apps))


def validated_definition(raw: WorkflowDefinition | dict[str, Any] | None) -> dict[str, Any]:
    definition = raw if isinstance(raw, WorkflowDefinition) else None
    if definition is None:
        if raw is None:
            definition = DEFAULT_DEFINITION
        else:
            definition = WorkflowDefinition.model_validate(raw)
    keys: set[str] = set()
    for step in definition.steps:
        if step.type not in ALLOWED_STEP_TYPES:
            raise AppError(
                f"Unknown workflow step type '{step.type}'.",
                code="invalid_step_type",
            )
        if step.key in keys:
            raise AppError("Workflow step keys must be unique.", code="duplicate_step_key")
        keys.add(step.key)
    return definition.model_dump()
