# DART Backend

The API-driven foundation described in `../architecture.md`: FastAPI, async
SQLAlchemy + PostgreSQL, Redis (cache + WebSocket fan-out), Celery (queue),
and a dedicated extension point for AI orchestration. **This is
infrastructure only** — there are no reconciliation endpoints yet. Every
route, middleware, and background-task wiring in this repo exists to be
built on, not extended by copy-paste; add new endpoint modules under
`app/api/v1/endpoints/`, new tasks under `app/tasks/`, new models under
`app/models/`.

**Starting to build the actual API?** See
[`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) — a full analysis of the old
Django backend's domain model, every `sp_master` operation it dispatched,
and a phased build order (identity/auth first, then recon core, then
security, then each pipeline stage).

## Tooling: uv only

No `venv`, no `pip`, no Poetry. [`uv`](https://docs.astral.sh/uv/) manages
the Python version, the virtual environment, and the dependency lockfile
(`uv.lock`) in one tool.

```bash
# one-time: install uv itself (skip if already installed)
# macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows:     powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

uv sync --dev          # creates .venv, installs runtime + dev dependencies
uv run uvicorn app.main:app --reload   # run the API locally
uv run pytest           # run tests
uv run ruff check .     # lint
uv run ruff format .    # format
uv run mypy app          # type-check (strict mode)
```

`uv add <package>` / `uv remove <package>` to change dependencies — never
hand-edit `uv.lock`.

## Local setup

1. `cp .env.example .env` and fill in `SECRET_KEY` (see the comment in the
   file for how to generate one) and `DATABASE_URL` if not using Docker.
2. Either run Postgres/Redis yourself and point `.env` at them — see
   [`docs/INSTALLATION.md`](docs/INSTALLATION.md) for full setup on
   Windows, Linux, and WSL, including where to get Redis on Windows
   (there's no official build) — or use Docker Compose (below) to get
   the whole stack in one command instead.
3. `uv run alembic upgrade head` to apply migrations (none exist yet
   beyond the empty baseline — this becomes meaningful once models are
   added under `app/models/`).

## Docker Compose (recommended for local dev)

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
docker compose up --build
```

- API: http://localhost:8080 (docs at `/docs`, since `ENVIRONMENT=local`) —
  mapped to host 8080 instead of 8000 since 8000 may already be in use
  locally; change the `api` port mapping in `docker-compose.yml` if you'd
  rather free up 8000 and use that instead.
- Flower (Celery monitoring): http://localhost:5555
- Postgres: `localhost:5432` (`dart`/`dart`/`dart`)
- Redis: `localhost:6379`

The `api` and `worker` services mount `./app` as a volume, so code changes
are picked up without rebuilding the image.

## What's already wired up

| Concern | Where | Notes |
|---|---|---|
| Async DB | `app/db/session.py` | Pooled async SQLAlchemy engine, `get_db` FastAPI dependency, tuned pool size for concurrent workers |
| Cache | `app/cache/redis.py` | Async Redis client, JSON get/set helpers, `get_redis` dependency |
| Queue | `app/tasks/celery_app.py` | Celery + Redis broker/backend (see `architecture.md` §4 for why this over RabbitMQ/SQS) |
| Real-time | `app/ws/` | WebSocket endpoint + Redis pub/sub fan-out, so it's correct across multiple API instances from day one |
| Auth | `app/core/security.py`, `app/api/deps.py` | JWT access/refresh tokens, Argon2 password hashing, `get_current_user` dependency. **`/auth/token` is scaffolding, not real auth** — see its docstring |
| Rate limiting | `app/core/rate_limit.py` | Redis-backed (shared across instances), with in-memory fallback if Redis is briefly unreachable |
| Security headers | `app/core/middleware.py` | CSP-adjacent headers, HSTS on HTTPS, request-ID correlation |
| CORS / hosts | `app/main.py`, `Settings` | Explicit allow-lists only — a wildcard origin is a config-time error, not a runtime footgun |
| Structured logging | `app/core/logging.py` | JSON in staging/prod, redacts anything that looks like a secret key by name |
| Error handling | `app/core/exceptions.py` | One response envelope for every error type; stack traces never reach the client |
| Config | `app/core/config.py` | Pydantic Settings, env-driven, fails startup on a missing secret rather than defaulting to something insecure |
| Migrations | `alembic/` | Async-aware `env.py`, reads `DATABASE_URL` from the same `Settings` the app uses — one source of truth |

## Adding AI orchestration later

`app/ai/base.py` defines an `Orchestrator` protocol; `app/ai/registry.py`
resolves a named implementation as a FastAPI dependency. Nothing else in
the codebase imports LangGraph (or anything else) directly. To wire in a
real orchestrator:

```python
# app/ai/langgraph_orchestrator.py
from app.ai.base import Orchestrator
from app.ai.registry import register


class LangGraphOrchestrator:
    name = "recon_draft"

    async def run(self, *, input, context=None): ...  # yield event dicts


register(LangGraphOrchestrator())
```

Then depend on it from a route with
`Depends(get_orchestrator("recon_draft"))`. See the module docstrings in
`app/ai/` for the full contract.

## Security notes worth knowing before extending this

- `/api/v1/auth/token` intentionally does not check a password — there is
  no user table yet. It 501s outside `DEBUG=true`/local. Wire it to a real
  user lookup + `verify_password()` before it's relied on for anything.
- Refresh tokens aren't revocable yet (no revocation store). Add a Redis
  set keyed by `jti` before shipping refresh-token support for real users.
- `docs_url`/`redoc_url`/`openapi.json` are automatically disabled in
  production (`Settings.docs_enabled`) — don't override that per-deployment
  without a reason.
- Every list-typed setting from the environment (`CORS_ORIGINS`,
  `ALLOWED_HOSTS`) uses `Annotated[list[str], NoDecode]` — if you add
  another list/dict setting, use the same pattern, or pydantic-settings
  will try to JSON-parse a plain comma-separated value and crash startup.
