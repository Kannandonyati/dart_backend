# KT — Phase 5: Run Import

Knowledge transfer for what was actually built, why it's shaped the way
it is, how to run/test/extend it, and what's deliberately left for
Phase 6+. Companion docs: `KT_PHASE1.md` through `KT_PHASE4.md`,
`../architecture.md` (the design this phase follows most directly —
see "Why it's shaped this way" below), `BUILD_PLAN.md`.

## The single most important decision this phase makes

The old backend stores imported row data in a Postgres table/view
created **dynamically per recon** via live DDL
(`recon_data.vw_app_<recon_id>`, one physical column per dimension —
confirmed directly in the old backend's own `query.sql`, which is the
one place its usually-opaque stored-procedure logic is actually
readable in this codebase). Every dimension add/rename fires a live
`ALTER TABLE` against that recon's table.

This is exactly the anti-pattern `architecture.md` §1/§2 is written
against — schema that only exists as DDL a live database ran, invisible
outside a `psql` session, impossible to partition or query uniformly
across recons. `architecture.md` §2 names the alternative directly:
*"audit/event history... is a better fit for Postgres JSONB columns on
a partitioned, insert-only table."*

**`ImportedRow.data` (a JSONB column, keyed by dimension name) is that
alternative.** One physical schema for every recon's imported data,
created once by a migration, never touched by DDL again. Not yet
physically `PARTITION BY`'d — that's a real Postgres migration step
bigger than this phase needs before there's real multi-recon volume to
justify it (see "Known gaps"), but `(recon_id, app_number)` is indexed,
and the JSONB-per-row shape is exactly what a future partition-by-
`recon_id` migration would sit on top of without a redesign.

## What's here

| Table | File | Purpose |
|---|---|---|
| `import_runs` | `app/models/import_run.py` | One row per uploaded file — status, row count, error message, timestamps |
| `imported_rows` | `app/models/import_run.py` | One row per data row, `data` JSONB keyed by dimension name |

| Module | File | Purpose |
|---|---|---|
| Validation | `app/services/import_validation.py` | Pure, framework-agnostic file validation + row parsing — ported faithfully from the old backend's genuinely well-designed `import_valid.py` |
| File storage | `app/services/file_storage.py` | Local-disk save/read/delete, isolated so a later swap to S3/Azure Blob touches one module |
| Celery task | `app/tasks/import_tasks.py` | The actual validate → bulk-insert work, run in the background |
| Endpoints | `app/api/v1/endpoints/imports.py` | `POST`/`GET /recons/{id}/imports`, `GET .../imports/{id}`, `GET .../imports/data` |

## Why it's shaped this way

**Upload is asynchronous — Celery's first real task.** The old
backend's `run_import/upload` does validate-then-load fully
synchronously inside the HTTP request (confirmed in its `views.py` — no
job/status table, no background mechanism at all; a 3M-row file would
mean a 3M-row-scan HTTP request). `app/tasks/celery_app.py` already had
working Celery infrastructure from before this phase (a health-check
task proving the worker/broker/backend wiring) — Phase 5 writes the
first real task into it and removes the health-check placeholder per
its own docstring's instruction. The upload endpoint does only the
cheap synchronous parts (recon/app validation, saving the file,
creating a `pending` `ImportRun`) and returns immediately; callers poll
`GET .../imports/{id}` for status.

**Validation is a faithful port, not a redesign** — unusually, for this
project, the old backend's `import_valid.py` is genuinely well-designed
(plain readable Python, not hidden behind `sp_master`), so
`app/services/import_validation.py` keeps its exact rules: the
delimiter must appear in the header, every configured dimension must
already exist (Dimension Linking, Phase 4, is a hard prerequisite — an
import can't run against an unconfigured app), the header's column
count must match the highest configured column position, and a blank
cell is only acceptable if that dimension also has a configured
default value. Whole-file validation before any write, matching the
all-or-nothing rule Phase 4 already established for its own CSV import.

**A dimension mapping can carry both a file column and a default value
at once — this is what makes the blank-cell-fallback rule expressible
at all.** Phase 4's schema already permitted this combination (nothing
required `default_value` to be empty when `in_file` is true); Phase 5
is the first phase to actually rely on it.

**Celery tasks get their own database engine, not the API's.** A real
bug, found and fixed during this phase's own development, not
theorized about: the shared module-level `engine`/`async_session_factory`
(`app/db/session.py`) is bound to whichever asyncio event loop is
running when its connections are first opened. This codebase's Celery
tasks are sync functions wrapping `asyncio.run(...)` — and `asyncio.run`
creates a **new** event loop on every single call, for the life of a
long-running worker process. Reusing the shared engine's pooled
connections across a second task invocation's (different) event loop
raised `RuntimeError: Future ... attached to a different loop` — caught
live via the Postman/Newman verification pass against a real worker,
not by inspection. Fixed with a new `celery_session_scope()`
(`app/db/session.py`) that creates and disposes a dedicated engine
inside each task's own event loop; `session_scope()` (used by
`app/db/seed.py`, safe there because that script only ever runs one
event loop for its whole process lifetime) is now explicitly documented
as unsafe for this use. Same underlying class of bug as Phase 1's KT's
documented pytest-asyncio event-loop gotcha, in a context pytest's
session-scoped-loop fixture doesn't reach.

**A `.delay()` call must not hang the request if the broker is briefly
unreachable.** Also found live, not theorized: with Celery's old
defaults, `run_import_task.delay(...)` retried connecting to a down
Redis broker indefinitely — the first attempt to run this phase's own
test suite blocked past a 120-second timeout. Fixed with
`broker_connection_timeout=2` / `broker_connection_max_retries=1` in
`celery_app.py` — a real production improvement (fail fast, let the
caller retry) as much as a fix for local development against a broker
that might not be running yet.

## Security properties (each has a test)

| Property | Why | Test |
|---|---|---|
| Every route requires authentication and recon ownership | Same shared `get_accessible_recon` check as every prior phase | `test_non_owner_cannot_upload_or_list_imports` |
| Uploading to an app that isn't configured is a clean 404 | Can't accidentally import into app slot 2 when only app 1 exists | `test_upload_to_unconfigured_app_is_404` |
| Zero dimensions configured blocks the import outright | Dimension Linking (Phase 4) is a hard prerequisite, not optional — matches the old backend exactly | `test_no_dimensions_configured_is_rejected` |
| A blank cell with no configured default fails the whole import, naming the exact row/column/dimension | No silent data loss, no partial import | `test_blank_cell_with_no_default_is_rejected_with_row_and_column`, `test_import_run_with_invalid_file_fails_with_error_message` |
| A failed import leaves zero rows written | Validated in full before any insert | `test_import_run_with_invalid_file_fails_with_error_message` (asserts `imports/data` is empty after a failed run) |
| The uploaded file is deleted after processing, success or failure | No unbounded disk growth from a `finally` block that always runs | `test_import_deletes_the_uploaded_file_after_processing` |
| A completed import's rows are readable back, correctly keyed by dimension name | The actual point of the JSONB design | `test_full_import_run_completes_and_rows_are_readable` |

108 tests total (30 Phase 1 + 15 Phase 2 + 30 Phase 3 + 18 Phase 4 + 9
validation unit tests + 6 Run Import integration tests), all passing
against a real `dart_test` Postgres database. The Celery task itself is
exercised directly in tests (`await _run_import(...)`, the same async
function the task wraps) rather than through a live worker — no worker
runs during the test suite, so `.delay()` only enqueues; this is
standard practice for testing Celery-backed code, and is a deliberate
choice, not a gap: the real worker path was independently verified via
the Postman/Newman collection against an actual running worker (see
below), which is exactly where the event-loop bug above was caught.

## Known gaps — explicit, not accidental (Phase 6+ / future work)

- **No physical `PARTITION BY recon_id` on `imported_rows` yet.** Real
  Postgres partitioning is a bigger migration than this phase needs
  before there's multi-recon data volume to justify it — the table is
  indexed on `(recon_id, app_number)` today, and its JSONB-per-row shape
  is exactly what a partition migration would sit on top of later
  without a redesign. Don't guess the partition strategy now; revisit
  when real volume makes it necessary.
- **No real 3M-row streaming/COPY-based ingestion.** Rows are parsed
  into memory and bulk-inserted via SQLAlchemy Core's multi-row
  `insert()` (a real, meaningful improvement over ORM object-per-row
  `add()`, but not Postgres's native `COPY` protocol). `architecture.
  md`'s "bulk-load via COPY... instead of row-by-row INSERTs" is the
  next optimization if this proves insufficient at real file-size
  scale — not built speculatively here.
- **No WebSocket/real-time progress push.** `architecture.md` §5
  describes FastAPI WebSockets + Redis pub/sub for live job progress;
  `BUILD_PLAN.md` specifically flags Phase 6 (Bridge Members) as "a good
  candidate for the already-scaffolded WebSocket progress layer" — Run
  Import uses polling (`GET .../imports/{id}`) instead, a smaller,
  complete, working piece rather than a half-built real-time layer.
- **`kickout`, `processed_flag`, `deleted_flag` on `ImportedRow` are
  columns, not yet behavior.** Confirmed real old-backend concepts
  (present on the equivalent old-backend table/view), included now so
  Phase 6 (Bridge Members, which reads and acts on `kickout`-flagged
  rows) doesn't need a schema migration to add them — but nothing in
  Phase 5 sets or reads them yet.
- **Local filesystem storage only**, and the API and Celery worker must
  share it. Fine for a single-machine deploy; a real multi-worker
  deployment needs S3/Azure Blob behind `app/services/file_storage.py`
  — a module swap, not a redesign, by design.
- **The reference frontend's Run Import page
  (`run-import-panel.tsx` and `src/features/recon-pipeline/api/*run-
  import*`) is NOT rewired to the new backend** — same scoping
  precedent as Phase 3 (Recon Security page) and Phase 4 (Dimension
  Linking page): backend, tests, and Postman collection complete;
  frontend rewrite is a separate, appropriately-sized follow-up.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # applies Phase 1-5 migrations
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload     # API
uv run celery -A app.tasks.celery_app worker --pool=solo --loglevel=info  # worker (--pool=solo is Windows-specific)
uv run pytest                             # 108 tests total, real dart_test Postgres, no mocks
```

Needs Redis running (`celery_broker_url`/`celery_result_backend` in
`.env`) for the worker and the upload endpoint's `.delay()` call to
succeed — without it, uploads still create a `pending` `ImportRun`
(the enqueue call fails fast per the timeout fix above) but nothing
ever processes them.

## Postman collection

`postman/DART_Backend_Phase5.postman_collection.json`, same environment
file as Phase 1-4, plus a checked-in fixture CSV
(`postman/fixtures/sample_import.csv`) the upload requests attach —
run Newman from the `Backend/postman/` directory so the relative path
resolves. **Requires a running Celery worker** consuming the same
broker; the "Poll status until completed" request retries up to 20
times (3s apart) via `setNextRequest`, since a real worker's processing
time is genuinely variable, not instant. Verified via Newman against a
live server and a live worker: 22/22 requests, 24/24 assertions
passing — including catching the event-loop bug above, which a
pytest-only pass would never have exercised (no live worker there).

```bash
cd Backend/postman
npx newman run DART_Backend_Phase5.postman_collection.json \
  --environment DART_Backend_Local.postman_environment.json
```

## Extending this (Phase 6+)

**Bridge Members (Phase 6)** reads/acts on `kickout`-flagged
`ImportedRow`s — the column exists, the matching logic that sets it
doesn't yet. `architecture.md`'s WebSocket + Redis pub/sub real-time
layer is also flagged there specifically; wire it there rather than
retrofitting it onto Run Import's polling now.

**Any future Celery task** must use `celery_session_scope()`
(`app/db/session.py`), never the plain `session_scope()` or the
module-level `engine`/`async_session_factory` directly — see "Why it's
shaped this way" above for the event-loop bug this avoids.
