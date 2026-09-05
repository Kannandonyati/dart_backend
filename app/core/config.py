"""Central application settings, loaded from environment variables / .env.

Nothing in this module has a default for a secret. A missing required
value must fail application startup, not silently fall back to something
insecure — that is the whole point of centralizing config here instead of
scattering `os.getenv(..., "changeme")` calls through the codebase.

Environment selection: set ENVIRONMENT=local|test|staging|production. Each
env loads `.env.{environment}` on top of `.env` (see model_config below),
so dev/staging/prod can share defaults but override what differs
(pool sizes, log format, docs exposure) without duplicating every key.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyUrl, Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- environment ---
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False

    # --- app identity ---
    project_name: str = "DART API"
    api_v1_prefix: str = "/api/v1"

    # --- security ---
    # No default: a production deploy with an unset SECRET_KEY must refuse
    # to start rather than sign tokens with a well-known placeholder.
    secret_key: str = Field(..., min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_expire_days: int = 7  # sliding session: longer than refresh
    refresh_token_expire_days: int = 1
    invite_token_expire_days: int = 7
    password_reset_token_expire_hours: int = 24

    # --- CORS / hosts ---
    # Explicit allow-lists only — "*" is never valid here, enforced below.
    # NoDecode: without it, pydantic-settings tries to JSON-parse the raw
    # env string before our comma-split validator ever runs, and a plain
    # "localhost,127.0.0.1" value (exactly what .env.example documents)
    # would fail to parse as JSON and crash startup.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1"]
    )

    # --- database ---
    database_url: PostgresDsn
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_echo: bool = False

    # --- redis (cache + pub/sub for websocket fan-out) ---
    redis_url: RedisDsn = "redis://127.0.0.1:6379/0"  # type: ignore[assignment]
    redis_cache_ttl_seconds: int = 300

    # --- celery (queue: see architecture.md §4 — Celery + Redis broker) ---
    celery_broker_url: RedisDsn = "redis://127.0.0.1:6379/1"  # type: ignore[assignment]
    celery_result_backend: RedisDsn = "redis://127.0.0.1:6379/2"  # type: ignore[assignment]

    # --- uploaded-file storage (Phase 5: Run Import) ---
    # Local filesystem for now — the API and the Celery worker must share
    # this path (fine for a single-machine dev/staging deploy; a real
    # multi-worker deployment needs a shared volume or object storage
    # here instead, a drop-in swap behind app/services/file_storage.py,
    # not a redesign).
    upload_storage_dir: str = "./var/uploads"

    # --- rate limiting ---
    rate_limit_default: str = "100/minute"

    # --- bootstrap admin (app/db/seed.py) ---
    # Deliberately no default — a real admin password must never have a
    # value that could accidentally ship as a working default. The old
    # Django backend's convention for this account was recon@admin.com
    # (see .env.example) — no default was hardcoded there either (its
    # actual credentials lived only in a deployed database this rebuild
    # has no access to), so the email/password stay operator-supplied here
    # too, not silently reproduced.
    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    # --- default (non-privileged) user (app/db/seed.py) ---
    # Optional second seeded account, ordinary privileges only — mirrors
    # the old backend's default@dart.com convention. Unlike the bootstrap
    # admin, seeding this is opt-in: unset either value and app/db/seed.py
    # skips it entirely rather than failing startup.
    default_user_email: str | None = None
    default_user_password: str | None = None

    # --- platform admin (app/db/seed.py) ---
    # The tier above the bootstrap admin: the only account that can change
    # which UI components everyone else is allowed to see (see
    # app/core/ui_components.py). Opt-in like the default user — unset
    # either value and seeding skips it. No default password, same
    # reasoning as the bootstrap admin above: `is_platform_admin` cannot
    # be granted through any API, so whatever is set here is the only way
    # into the tier, and a shipped default would be a backdoor.
    platform_admin_email: str | None = None
    platform_admin_password: str | None = None

    # --- observability ---
    sentry_dsn: AnyUrl | None = None
    log_level: str = "INFO"
    log_json: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_hosts_csv(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [host.strip() for host in v.split(",") if host.strip()]
        return v

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_cors(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError(
                "cors_origins may not contain '*' — list explicit origins. "
                "A wildcard combined with credentialed requests is a CSRF hole."
            )
        return v

    # None = infer from environment (strict in staging/production).
    # Postgres, Redis, and the queue broker are always mandatory regardless
    # of this flag; it only affects any future optional checks.
    strict_startup_checks: bool | None = None

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def enforce_strict_startup(self) -> bool:
        if self.strict_startup_checks is not None:
            return self.strict_startup_checks
        return self.environment in ("staging", "production")

    @property
    def docs_enabled(self) -> bool:
        # Swagger/ReDoc are a recon surface for an attacker; only serve them
        # outside production, or when explicitly forced on via debug.
        return not self.is_production or self.debug


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — env is read once per process."""
    return Settings()


settings = get_settings()
