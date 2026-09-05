# KT — Phase 2: Recon Core

Knowledge transfer for what was actually built, why it's shaped the way
it is, how to run/test/extend it, and what's deliberately left for
Phase 3+. Companion docs: `KT_PHASE1.md` (Identity & Auth, which this
phase builds directly on top of), `../architecture.md`, `BUILD_PLAN.md`,
`INSTALLATION.md`.

## What's here

Two tables, one endpoint group, no new permissions plumbing (Phase 1's
`require_privilege` is reused as-is):

| Table | File | Purpose |
|---|---|---|
| `recons` | `app/models/recon.py` | The core reconciliation-run record — name, description, owner, status, soft-delete timestamp |
| `recon_group_xref` | `app/models/recon.py` | M2M join to `groups`, wired into queries now, populated by nothing until Phase 3 |

| Endpoint group | File | Routes |
|---|---|---|
| Recons | `app/api/v1/endpoints/recons.py` | `POST /recons`, `GET /recons`, `GET /recons/available`, `GET /recons/{id}`, `PATCH /recons/{id}`, `DELETE /recons/{id}` |

## Why it's shaped this way

**Ownership, not group membership, is the access model for now.** A
recon is fully owned by the user who created it. Only two things widen
that: `is_superuser` (Phase 1's bootstrap break-glass flag) and the
`recon:manage_all` privilege (new this phase, seeded onto "Account
Admin" — see `app/db/seed.py`). There is deliberately no group-based
sharing yet, even though the `recon_group_xref` table and
`GET /recons/available` route both exist today — see "Known gaps"
below for why that's not a bug.

**Every not-found-or-not-yours case is a 404, never a 403** — same
enumeration-resistance reasoning as Phase 1's login endpoint. A 403 on
`GET /recons/{id}` would tell a caller "this id is real, you just can't
see it," which is itself a leak for someone probing ids. All four
by-id routes share one code path, `_get_owned_or_manageable()`, so this
rule can't be forgotten on one route and kept on another. Verified: a
genuinely nonexistent id and an existing-but-someone-else's id return
byte-identical error bodies (`test_response_never_leaks_recon_id_of_nonexistent_recon_differently`).

**Delete is soft, not hard.** `DELETE /recons/{id}` sets `deleted_at`
rather than removing the row. Every list/get query filters
`deleted_at.is_(None)`, so a deleted recon disappears from the API
exactly as if it were gone — but the audit trail (and any future
"restore" feature) stays possible. The live-only unique index on
`name` (`uq_recons_name_live`) lets a deleted name be created again;
without it the Select list looks empty while `POST /recons` still 409s.
A second delete of the same recon
correctly 404s rather than silently no-op'ing 204 again — soft-deleted
recons are excluded from `_get_owned_or_manageable`'s query, so they're
just as invisible to a repeat `DELETE` as to a `GET`.

**Recon identity is a UUID, not the name.** Names are renameable and
must stay unique among *non-deleted* recons, so nothing can key off
name long-term. This mattered directly in the frontend integration —
the old backend's downstream pipeline stages (Dimension Linking, Run
Import, etc.) all thread a recon by name, a decision this phase didn't
revisit; see "Frontend integration" below for the seam that creates.

## Security properties (each has a test — don't remove the test when
touching the code it covers)

| Property | Why | Test |
|---|---|---|
| Every route requires authentication | No anonymous recon access, full stop | `test_create_recon_requires_authentication` |
| 404-not-403 for someone else's recon | A 403 confirms existence to a caller with no legitimate way to know that | `test_non_owner_gets_404_not_403_for_someone_elses_recon` |
| Nonexistent id and forbidden id are indistinguishable | Same status, same error code, same message | `test_response_never_leaks_recon_id_of_nonexistent_recon_differently` |
| Ownership check gates get/rename/delete uniformly | One shared helper, not three separate hand-rolled checks | `test_non_owner_cannot_rename_someone_elses_recon`, `test_non_owner_cannot_delete_someone_elses_recon` |
| `recon:manage_all` privilege widens access correctly, without over-widening | A user with the privilege can reach any recon; a user without it still can't | `test_user_with_recon_manage_all_privilege_can_get_any_recon` |
| `is_superuser` bypasses ownership, same as Phase 1's break-glass rule | Consistency with the one existing bypass, not a second ad-hoc one | `test_superuser_can_get_any_recon` |
| Soft delete actually hides the recon everywhere | Not just from `GET` — from the list too | `test_delete_is_soft_and_hides_from_list_and_get` |
| A deleted recon's name can be reused | Uniqueness is among live recons only (partial unique index), matching the list which already hides deleted rows | `test_deleted_recon_name_can_be_reused`, `test_rename_onto_a_deleted_recon_name_is_allowed` |
| A failed delete attempt doesn't silently corrupt state | Confirms the recon is genuinely untouched after a non-owner's delete 404s | `test_non_owner_cannot_delete_someone_elses_recon` |
| Concurrent duplicate-name creation doesn't 500 | Check-then-insert race, same pattern (and same fix) as Phase 1's `create_user` | `test_concurrent_duplicate_recon_creation_never_500s` |
| `list_available_recons` returns empty, not an error, before group-linking exists | A structurally-correct query against an empty relationship must not be treated as a bug | `test_list_available_is_empty_until_group_linking_exists` |

## Bugs found and fixed *while building this* (not pre-existing — caught
during Phase 2 itself, via live pytest runs against a real database, not
just code review)

1. **Seed script silently failed to sync new privileges onto existing
   roles.** Adding `recon:manage_all` to `_BASELINE_PRIVILEGES` created
   the `Privilege` row on re-seed but never linked it to the
   already-existing "Account Admin" `Role` — the seed loop only wired
   privileges when *creating* a role, not when one already existed.
   Found by directly querying the database (not trusting the seed
   script's own log output), since a passing log line was exactly what
   masked the bug. Fixed with an `else` branch in `app/db/seed.py` that
   diffs `wanted` privileges against `existing_role.privileges` (eager-
   loaded via `selectinload` — a bare relationship access threw
   `MissingGreenlet` in async context otherwise) and extends the
   relationship with whatever's missing. Verified idempotent: a third
   seed run is a confirmed no-op.
2. **`db.refresh(recon, attribute_names=["owner", "groups"])` caused a
   `MissingGreenlet` crash on `updated_at` access.** Restricting
   `attribute_names` on `Session.refresh()` expires the *whole*
   instance but only reloads the named attributes — `updated_at` was
   left expired-but-unloaded, and the next access (`_to_read()`'s
   `last_modified=recon.updated_at`) tried an implicit lazy-load outside
   an async-safe greenlet context and crashed. Found via the actual
   failing pytest traceback for `test_owner_can_rename_their_recon`, not
   by inspection. Fixed by replacing both refresh call sites
   (`create_recon`, `update_recon`) with a `_reload()` helper that does
   a fresh, fully-eager-loaded `SELECT` instead of a partial refresh.

## Known gaps — explicit, not accidental (Phase 3+ work)

- **`GET /recons/available` always returns `[]` today.** It's wired
  correctly against `recon_group_xref`/`Membership`, but nothing can
  populate `recon_group_xref` until Phase 3 builds the group-management
  and recon-sharing endpoints. Not a bug — see
  `test_list_available_is_empty_until_group_linking_exists`.
- **No group picker on create/edit.** The frontend's create/edit recon
  dialogs deliberately have no group field (removed as part of this
  phase's frontend integration) for the same reason — there's nothing
  real to pick from yet.
- **No archive endpoint.** The `archived` column exists and is returned
  by the API, but nothing sets it to `true` yet.
- **No bulk operations, no recon-level audit log beyond `updated_at`.**
- **Status is a free string (`"Created"` by default), not an enum or a
  state machine.** Nothing here transitions it yet — that arrives with
  Run Import / Transformation / Run Report in later phases.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # applies both Phase 1 and Phase 2 migrations
uv run python -m app.db.seed             # idempotent — also syncs recon:manage_all onto Account Admin
uv run uvicorn app.main:app --reload     # run the API
uv run pytest                             # 45 tests total (30 Phase 1 + 15 Phase 2), real dart_test Postgres, no mocks
```

## Postman collection

`postman/DART_Backend_Phase2.postman_collection.json`, using the same
`DART_Backend_Local.postman_environment.json` as Phase 1. Self-contained
— it logs in as the bootstrap admin itself to provision two fresh users
(`recon-a@dart.com` / `recon-b@dart.com`), so it does not depend on
Phase 1's collection having been run first, or on running before it.
Verified via Newman against a live server: 20/20 requests, 27/27
assertions passing.

```bash
npx newman run Backend/postman/DART_Backend_Phase2.postman_collection.json \
  --environment Backend/postman/DART_Backend_Local.postman_environment.json
```

**Heads up:** running the full collection twice creates `recon-a@dart.com`
and `recon-b@dart.com` only once (the Setup folder tolerates a 409 on
re-creation), but `Q1_GL_Recon` will already exist from the first run's
"Create recon" step racing against the still-present row from a prior
partial run if the final Delete step didn't complete — re-run the
"Recons — Delete" folder alone first if you need a clean slate, or pick
a fresh recon name for a manual re-run.

## Frontend integration

Phase 1 (auth) and Phase 2 (recon Select stage) are both wired into the
real React app as of this phase, coexisting with the still-untouched old
Django backend via a strangler-fig split:

- `src/lib/dart-api-client.ts` — new axios client, `VITE_DART_API_URL`,
  attaches the Zustand-stored access token. Everything below uses this
  client. Everything else in the app still uses the old `apiClient`.
- Sign-in (`src/features/auth/sign-in/login-request.ts`) now calls
  `POST /api/v1/auth/login` then `GET /api/v1/users/me` on the new
  backend. `role` is hardcoded to `[]` in the returned user object —
  Phase 1/2 have no role-to-frontend-permission mapping yet, so any
  UI that gates on `user.role` will not see a populated list. Grep for
  `.role` usages before relying on it anywhere new.
- Recon Pipeline's "Select" stage (`src/features/recon-pipeline/`) —
  create/list/rename/delete all call the new backend's `/api/v1/recons*`
  routes. The group `<Select>` field was removed from both the create
  and edit dialogs (`create-recon-dialog.tsx`, `edit-recon-dialog.tsx`)
  since there's nothing real to populate it with (see "Known gaps").
- **The seam**: every pipeline stage *after* Select (Dimension Linking,
  Run Import, Bridge Members, Transformation, Run Report) is still
  entirely on the old Django backend, and threads the active recon by
  *name*, not id — a decision inherited from the old backend's schema,
  not introduced here. A recon created via the new backend's Select
  stage hands its name to those old-backend stages exactly as before,
  but the old backend has no row for it, so any old-backend call that
  needs recon-scoped data (e.g. Dimension Linking's application list)
  correctly fails with a clean "couldn't load" error rather than
  silently returning wrong data. This is the expected, honest boundary
  of a Phase 1/2-only integration, verified live in a real browser, not
  just reasoned about. It closes once Run Import (or whichever phase
  migrates that stage) exists on the new backend and the two systems
  share one source of truth for recons.

## Extending this (Phase 3+)

**Adding group-based recon sharing:** `recon_group_xref` and
`GET /recons/available`'s query are already correct — Phase 3 only
needs to add the endpoints that *write* rows into
`recon_group_xref` (linking a recon to a group) plus the group CRUD
endpoints themselves (`Lob`/`Team`/`Group` tables already exist per
Phase 1's KT). No changes needed in `recons.py`.

**Adding recon-level privilege gating beyond `recon:manage_all`:**
follow Phase 1's `require_privilege(name)` pattern — see
`KT_PHASE1.md`'s "Extending this" section. `_can_manage()` in
`recons.py` is the one place to add a new bypass condition if a more
granular privilege (e.g. `recon:manage_own_lob`) is ever needed instead
of the current all-or-nothing `recon:manage_all`.

**Migrating another pipeline stage onto the new backend:** follow this
phase's pattern — new SQLAlchemy model + Alembic migration, Pydantic
schemas, router, real-database tests covering the ownership/404 rules
this phase established, then a matching frontend API module under
`src/features/recon-pipeline/api/` pointed at `dartApiClient`. Consider
switching the stage-to-stage handoff from name-based to id-based while
migrating a stage — the current name-based threading (see "The seam"
above) is inherited debt, not a design to replicate further.
