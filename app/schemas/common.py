"""Response shapes shared across endpoints — input validation for outputs
matters too: a hand-built dict response can silently drift from what the
frontend expects, a Pydantic response_model can't."""

from pydantic import BaseModel


class HealthComponent(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class HealthResponse(BaseModel):
    status: str
    components: list[HealthComponent]


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 spec constant, not a secret
    audit_status: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str | None = None
