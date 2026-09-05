"""SSO provider and audit-log shapes. Secrets never leave the API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SsoProviderUpsert(BaseModel):
    provider_key: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=200)
    client_id: str = Field(min_length=1, max_length=500)
    client_secret: str | None = None
    discovery_url: str = Field(min_length=1, max_length=500)
    extra_params: dict[str, Any] = Field(default_factory=dict)
    logo_key: str = Field(default="custom", max_length=80)
    is_enabled: bool = True


class SsoProviderPublic(BaseModel):
    provider_key: str
    display_name: str
    client_id: str
    discovery_url: str
    extra_params: dict[str, Any]
    is_enabled: bool
    logo_key: str


class SsoProviderManaged(SsoProviderPublic):
    has_secret: bool
    created_at: datetime
    updated_at: datetime


class SsoExchangeRequest(BaseModel):
    provider_key: str = Field(min_length=1, max_length=80)
    code: str = Field(min_length=1)
    code_verifier: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)


class SsoAuditLogRead(BaseModel):
    provider_key: str
    email: str
    username: str | None
    success: bool
    message: str
    created_at: datetime
