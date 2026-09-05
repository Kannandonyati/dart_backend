# KT — Phase 1: Identity & Auth

Knowledge transfer for what was actually built, why it's shaped the way
it is, how to run/test/extend it, and what's deliberately left for
Phase 2+. Companion docs: `../architecture.md` (target stack),
`BUILD_PLAN.md` (the 9-phase roadmap this is Phase 1 of),
`INSTALLATION.md` (environment setup).

## What's here

Eight tables, three endpoint groups, one permissions framework:

| Table | File | Purpose |
|---|---|---|
| `users` | `app/models/user.py` | Real user identity — email/username/Argon2-hashed password |
| `lobs`, `teams`, `groups` | `app/models/security.py` | The org hierarchy (Department→Team→Group), tables exist now, CRUD endpoints are Phase 3 |
| `roles`, `privileges`, `role_privileges` | `app/models/security.py` | Fine-grained permission strings grouped into named roles |
| `memberships` | `app/models/security.py` | "This user holds this role within this scope" — the authorization backbone |

| Endpoint group | File | Routes |
|---|---|---|
| Auth | `app/api/v1/endpoints/auth.py` | `POST /auth/login`, `POST /auth/token` (OAuth2 form, for Swagger), `POST /auth/refresh` |
| Users | `app/api/v1/endpoints/users.py` | `GET /users/me`, `POST /users`, `GET /users`, `GET /users/{id}` |
| Permissions | `app/core/permissions.py` | `require_privilege(name)` — the dependency every privilege-gated route uses |

## Why it's shaped this way

**Membership is one polymorphic table, not six.** The old backend
(`docs/BUILD_PLAN.md` §3) had `group_admin`, `group_member`,
`team_admin`, `team_member`, `lob_admin`, `lob_member` — six near-
identical M2M tables. `Membership(user_id, scope_type, scope_id,
role_id)` replaces all six with one well-indexed table and one code
path (`user_has_privilege` in `app/core/permissions.py`) to test.
Trade-off made explicitly, not by accident: **scope inheritance isn't
implemented** — a Team-level role does *not* automatically grant access
to Groups under it. Every check today is an exact scope match. Extend
`user_has_privilege` when that's actually needed; don't guess the shape
now.

**`is_superuser` is a break-glass bootstrap flag, not a role.** There's
no admin *role* wired to real privileges yet by default — the seeded
bootstrap account bypasses `require_privilege` entirely via this
boolean (see `app/models/user.py`'s comment on the field). Real
users should get privileges through `Membership` once Phase 3's group-
management endpoints exist. Don't grant `is_superuser` to anyone but the
one bootstrap account.

**`get_current_user` hits the database on every request, not just the
token signature.** A JWT is valid (signature + expiry) independent of
whether the account it names still exists or is active — trusting the
token alone means a deactivated user's existing access token keeps
working until it naturally expires (up to 15 minutes, per
`ACCESS_TOKEN_EXPIRE_MINUTES`). This was verified live, not just
reasoned about: deactivating a user mid-session immediately 401s their
existing, unexpired token (`tests/test_auth.py::test_deactivating_a_user_immediately_invalidates_their_existing_token`).

**Two login routes, one shared check.** `/auth/token` (OAuth2 form) only
exists because Swagger's built-in "Authorize" button speaks
`OAuth2PasswordRequestForm` and nothing else. `/auth/login` (plain JSON)
is what real clients — the frontend, Postman — should use. Both call the
same `_authenticate()` helper in `auth.py`.

## Security properties (each has a test — don't remove the test when
touching the code it covers)

| Property | Why | Test |
|---|---|---|
| Argon2 hashing, real per-user salt | Old backend used one hardcoded salt for every user (`make_password(password, salt='dart')`) — defeats salting entirely | N/A (structural — see `app/core/security.py`) |
| Timing-attack resistant login | Password verification runs against a fixed dummy hash even when no user matches, so "no such user" and "wrong password" take equal time | implicit in identical-error test below |
| Identical error for every login failure mode | Distinct messages for "no such user" vs "wrong password" is itself an enumeration oracle | `test_login_fails_for_nonexistent_email_with_identical_error` |
| Login rate-limited tighter than global default (5/min vs 100/min) | The endpoint an online guesser actually wants gets the tightest limit | `tests/test_rate_limit.py` (deliberately re-enables the limiter — see below) |
| Rate limiter fails open to in-memory, not down | A dead Redis used to crash *every* request (slowapi's handler chokes on `ConnectionError`, not just `RateLimitExceeded`) — found and fixed this phase | manual — see `app/core/rate_limit.py`'s comment |
| Deactivation revokes existing tokens immediately | Not just at next expiry | `test_deactivating_a_user_immediately_invalidates_their_existing_token` |
| Refresh token type-confusion rejected | An access token must not work at the refresh endpoint even though it's validly signed | `test_refresh_rejects_an_access_token_used_as_refresh_token` |
| `UserRead` never serializes `hashed_password` | Not omitted by convention — the field doesn't exist on the schema at all | `test_response_never_contains_hashed_password` |
| Mass-assignment safe | `UserCreate` whitelists exactly `email`/`username`/`password` — can't inject `is_superuser`/`is_active` via the create endpoint | structural (schema-enforced) |
| Weak-password rejection doesn't crash | All-digits password used to 500 (`Object of type ValueError is not JSON serializable`) instead of a clean 422 — found and fixed this phase | `test_creating_a_user_with_an_all_digit_password_is_rejected_cleanly` |
| Concurrent duplicate creation doesn't crash | Check-then-insert has a TOCTOU race; the DB unique constraint is the real backstop, caught and converted to a clean 409 — found and fixed this phase | `test_concurrent_duplicate_creation_never_500s` |
| `require_privilege` denies by default | No membership = no privilege, full stop; `is_superuser` is the only bypass | `test_permissions.py`, `test_list_users_requires_privilege` |
| Privilege grants don't leak between users | Granting user A a privilege must not affect user B | `test_granting_privilege_to_one_user_does_not_leak_to_another` |

## Bugs found and fixed *while building this* (not pre-existing — these
were introduced and caught during Phase 1 itself, via live testing, not
just code review)

1. **`pydantic-settings` JSON-decoding list env vars before validators
   run** — `.env.example`'s own documented `ALLOWED_HOSTS=localhost,
   127.0.0.1` format would crash startup. Fixed with `Annotated[list[str],
   NoDecode]` (pre-Phase-1, but worth knowing — same pattern would bite
   any new list-typed setting).
2. **Rate limiter crashed every request on a Redis outage** instead of
   degrading — fixed with `in_memory_fallback_enabled=True`.
3. **`RequestValidationError` handler crashed (500) on a custom
   `field_validator`'s `ValueError`** — Pydantic embeds the raw exception
   *instance* in `errors()`'s `ctx`, which isn't JSON-serializable.
   Fixed by routing through `jsonable_encoder` in
   `app/core/exceptions.py`.
4. **`create_user`'s duplicate check was check-then-insert** — a real
   race under concurrent identical requests. Fixed by catching
   `IntegrityError` around the commit and converting it to the same
   clean 409 the pre-check already gives.
5. **Windows + asyncpg + pytest-asyncio event-loop mismatch** — not a
   security bug, but broke every DB-touching test with opaque
   `AttributeError`s on connection teardown. `app.db.session.engine` is
   a module-level singleton; pytest-asyncio's default is a new event
   loop per test function, and reusing pooled connections across event
   loops breaks asyncpg's Windows proactor sockets. Fixed with
   `asyncio_default_fixture_loop_scope = "session"` **and**
   `asyncio_default_test_loop_scope = "session"` in `pyproject.toml`
   (both are needed — newer `pytest-asyncio` separates fixture-loop
   scope from test-loop scope).

## Known gaps — explicit, not accidental (Phase 2+ work)

- **No refresh-token revocation store.** `/auth/refresh` issues a new
  refresh token without invalidating the old one. A stolen refresh
  token stays valid for its full 7-day life (`REFRESH_TOKEN_EXPIRE_DAYS`)
  with no way to cut it off early. Needs a Redis set keyed by `jti`,
  checked (and the old `jti` added to it) on every refresh.
- **No scope inheritance in `Membership`.** See "Why it's shaped this
  way" above.
- **`Lob`/`Team`/`Group` have no CRUD endpoints yet** — tables exist
  (Phase 1 scope per `BUILD_PLAN.md`), management endpoints are Phase 3.
- **No password reset / change-password flow.** Not built yet — the
  only way to set a password today is at user creation.
- **JWT is HS256 (single shared secret).** Fine for a monolith; revisit
  (RS256 + JWKS) only if/when another service needs to verify tokens
  independently.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # apply the Phase 1 migration
uv run python -m app.db.seed             # create the bootstrap admin (needs BOOTSTRAP_ADMIN_EMAIL/PASSWORD in .env)
uv run uvicorn app.main:app --reload     # run the API
uv run pytest                             # 30 tests, all against a real dart_test Postgres database — no mocks
```

Tests need a dedicated `dart_test` database (same `dart` role, separate
database from your dev `dart` db) — see `INSTALLATION.md` if it doesn't
exist yet: `CREATE DATABASE dart_test OWNER dart;`. Tests create every
table fresh at session start and `TRUNCATE` between tests — real
Postgres, not SQLite, not mocks.

## Postman collection

`postman/DART_Backend_Phase1.postman_collection.json` +
`DART_Backend_Local.postman_environment.json`. Import both, set
`bootstrap_admin_email`/`bootstrap_admin_password` in the environment to
match your `.env`, run the collection top-to-bottom.

**Heads up:** the walkthrough logs in ~4 times (bootstrap admin, wrong-
password check, OAuth2-form login, new-user login). Running the full
collection twice within the same minute will trip the real 5/minute
login rate limit on the second run — that's the rate limiter working
correctly, not a bug in the collection. Wait ~60s between full runs, or
run individual folders instead of the whole thing back-to-back.

## Extending this (Phase 2+)

**Adding a new privilege-gated endpoint:**
```python
@router.post("/recons", dependencies=[require_privilege("recon:create")])
async def create_recon(...): ...
```
No new plumbing needed — `require_privilege` and `CurrentUser` already
handle the rest. Seed the new privilege name onto whichever role should
have it in `app/db/seed.py`'s `_BASELINE_ROLES`, or (once Phase 3 exists)
grant it via a real `Membership` through the group-management endpoints.

**Adding a new model:** add it to `app/models/`, import it in
`app/models/__init__.py` (this is what makes Alembic autogenerate see
it — see that file's docstring), then `uv run alembic revision
--autogenerate -m "..."` and review the generated migration before
applying — autogenerate does not create the Postgres ENUM-type drop in
`downgrade()` for any new `Enum` columns; add it by hand the same way
`c9355aad973f_phase1_identity_auth.py`'s downgrade does, or a
downgrade→upgrade cycle will fail the second time around.
