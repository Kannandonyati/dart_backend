"""Request/response shapes for the UI component console."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.ui_component import EVERYONE_AUDIENCE
from app.models.user import USER_TYPE_VALUES

AUDIENCE_VALUES = (EVERYONE_AUDIENCE, *USER_TYPE_VALUES)


class AudienceState(BaseModel):
    audience: str
    is_enabled: bool
    updated_by: str | None = None
    updated_at: datetime | None = None


class ComponentEntry(BaseModel):
    """One catalog entry plus whatever has been decided about it."""

    key: str
    label: str
    kind: str
    parent: str | None
    description: str | None
    locked: bool
    platform_only: bool
    api_prefixes: list[str]
    enabled_for_everyone: bool
    """The baseline: the `everyone` override if one exists, else True."""
    overrides: list[AudienceState]
    """Per-user-type decisions only — the baseline is above, not repeated
    here, so a client rendering the advanced controls doesn't have to
    filter it back out."""


class ComponentCatalog(BaseModel):
    components: list[ComponentEntry]
    audiences: list[str]


class ComponentVisibility(BaseModel):
    """What the current user may see. `visible_keys` is an allow-list —
    see visible_component_keys() for why that direction."""

    visible_keys: list[str]
    is_platform_admin: bool


class ComponentSettingUpdate(BaseModel):
    is_enabled: bool
    audience: str = Field(default=EVERYONE_AUDIENCE)

    @field_validator("audience")
    @classmethod
    def _known_audience(cls, v: str) -> str:
        if v not in AUDIENCE_VALUES:
            raise ValueError(f"Unknown audience: {v}. Expected one of {', '.join(AUDIENCE_VALUES)}")
        return v


class ComponentSettingReset(BaseModel):
    audience: str = Field(default=EVERYONE_AUDIENCE)

    @field_validator("audience")
    @classmethod
    def _known_audience(cls, v: str) -> str:
        if v not in AUDIENCE_VALUES:
            raise ValueError(f"Unknown audience: {v}. Expected one of {', '.join(AUDIENCE_VALUES)}")
        return v
