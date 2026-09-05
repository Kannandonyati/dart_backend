# KT — Phase 6: Bridge Members

Knowledge transfer for what was actually built, why it's shaped the way
it is, how to run/test/extend it, and what's deliberately left for
Phase 7+. Companion docs: `KT_PHASE1.md` through `KT_PHASE5.md`,
`../architecture.md`, `BUILD_PLAN.md`.

## The core correction this phase made to its own starting assumption

Before any code was written, the natural guess — "a bridge member is a
matched pair of rows across two apps" — was checked against the old
backend's actual `bridge_members` source and turned out wrong. A bridge
member is a **crosswalk entry**: `(recon, app_number, dimension_name,
source_member) → bridge_member`, normalizing each app's raw dimension
values (e.g. two different account-numbering schemes) to one canonical
name *before* any cross-system matching happens. `AMOUNT` is
deliberately excluded — confirmed via a hardcoded filter in the old
backend's `bridge_list.py` with the comment *"Measure role... is not a
bridge member dimension"* — it's the value being reconciled, not a
matching key.

## What's here

| Table | File | Purpose |
|---|---|---|
| `bridge_mappings` | `app/models/bridge.py` | The crosswalk: `(recon, app_number, dimension_name, source_member) → bridge_member` |
| `bridge_runs` | `app/models/bridge.py` | Status/progress tracking for the Celery computation, same shape as Phase 5's `ImportRun` |

| Module | File | Purpose |
|---|---|---|
| Mapping CRUD | `app/api/v1/endpoints/bridge_mappings.py` | Create/list/update/delete, `/default` (identity seeding), `/import` (CSV upsert) |
| Bridge run | `app/api/v1/endpoints/bridge_runs.py` | Start/list/get status |
| Bridge data | `app/api/v1/endpoints/bridge_data.py` | Read-back: raw + resolved values + kickout flag, filterable |
| Celery task | `app/tasks/bridge_tasks.py` | The actual per-row resolution + kickout computation |

## Why it's shaped this way

**The "kickout" sentinel is reused, not reinvented.** The old backend
marks a crosswalk entry as unresolved by literally setting
`bridge_member = "kickout"` (confirmed in `kickout_list.py`, matched
case-insensitively) rather than a separate boolean column. Kept exactly
that way here (`BridgeMapping.bridge_member` is free text either way;
a redundant `is_kickout_mapping` column would just be a second source
of truth for the same fact) — `BridgeMappingRead.is_kickout` is a
computed field, not a stored one.

**`ImportedRow.kickout` (added in Phase 5, unused until now) is exactly
what `run_bridge` computes.** Confirmed the old backend has this same
split: the crosswalk's own "kickout" sentinel marks an *unmapped
value*; a separate, real `kickout` column on the *post-computation
joined dataset* marks a *row* that couldn't be fully resolved. Phase 5
added the column anticipating this; Phase 6 is the first thing that
writes to it.

**Resolved canonical values are computed at read time, not persisted.**
`bridge-data`'s response joins `ImportedRow.data` against
`BridgeMapping` on the fly. A mapping can change after the fact (fix a
typo, add a missing entry) without needing to re-run the whole
computation just to see the corrected values reflected — only
`kickout` (a real per-row, per-run *decision*, not a pure function of
the current mapping table) is written back by the task.

**The bridge-mapping CSV import format is new-backend-defined, not
ported.** The old backend's `bridge_import.py` only validates a column
count (`> 4`) before handing the raw file to an opaque stored-procedure
call — the actual per-column parsing isn't readable anywhere in this
repository, confirmed by reading it directly rather than assumed. Google
"guess the binary format" is worse than defining one: this phase
specifies five explicit columns (`app_number, dimension_name,
source_member, bridge_member, flip_sign, bridge_comment`) matching
`BridgeMappingCreate`'s own fields. Documented as a decision, same
category as Phase 5's JSONB storage choice.

**Bridge mapping import is upsert-merge, not full-replace** — unlike
Phase 4's dimension-config import, which *is* a full replace. The
difference is real, not arbitrary: a dimension list has no meaningful
"partial update" (every dimension must be redeclared with both apps'
mappings each time), but a crosswalk is naturally incremental — importing
a correction file for ten rows shouldn't touch the other thousand.

**`run_bridge` is Celery's second real task, using the same
`celery_session_scope()` fix Phase 5's KT documents** (the event-loop
bug: a fresh `asyncio.run()` per task invocation can't reuse the API's
module-level connection pool). The bulk `kickout` write-back uses
SQLAlchemy 2.0's "ORM Bulk UPDATE by Primary Key" form — found the
correct usage live, not from documentation alone: a first attempt using
an explicit `.where(ImportedRow.id == bindparam(...))` raised `No
primary key value supplied`, because that's a different code path from
the by-PK batch form, which instead wants bare `update(Entity)` plus a
list of dicts keyed by the actual PK attribute name.

**WebSocket progress reuses the existing scaffold (`app/ws/`) and adds
the ownership scoping its own docstring flagged as a TODO.** The
scaffold's `/ws/{channel}` endpoint authenticates but doesn't scope
channels to their owner — explicitly deferred there "until there are
real jobs to report progress on." Phase 6 is that job: `bridge_run:
{id}` channels now check, via the same `get_accessible_recon` every
HTTP endpoint on that recon already uses, that the connecting user
actually owns (or has `recon:manage_all` for) the run's recon before
allowing the subscribe. Other channel names remain unscoped, same as
before — scope the next real job type the same way when it lands.

## Security properties (each has a test)

| Property | Why | Test |
|---|---|---|
| Every route requires authentication and recon ownership | Same shared `get_accessible_recon` as every prior phase | `test_non_owner_cannot_manage_bridge_mappings`, `test_non_owner_cannot_start_or_read_bridge_runs` |
| AMOUNT cannot be bridge-mapped | It's the measure, not a matching key — enforced server-side, not just left to convention | `test_amount_dimension_cannot_be_mapped` |
| A crosswalk entry mapping to the `"kickout"` sentinel is reported as such | `is_kickout` computed correctly, case-insensitively | `test_kickout_sentinel_is_reported_as_is_kickout` |
| Default (identity) seeding never overwrites a real mapping | Only fills genuinely missing entries | `test_default_bridge_mappings_does_not_overwrite_existing` |
| Default seeding never touches AMOUNT | Same exclusion enforced in the bulk path, not just the single-create path | `test_default_bridge_mappings_creates_identity_mappings_from_imported_data` |
| CSV import is upsert, not destructive | Existing mappings not in the file survive | `test_import_bridge_mappings_upserts` |
| A row with any unmapped (or kickout-sentinel-mapped) dimension is flagged `kickout` | The actual point of the computation | `test_bridge_run_flags_unmapped_rows_as_kickout` |
| Bridge data is filterable by kickout status | Backs a "show me what still needs mapping" view | `test_bridge_data_can_filter_by_kickout` |
| A WebSocket subscriber must own the bridge run's recon | The scoping gap the scaffold's own docstring flagged, closed here — a stranger cannot watch another user's job progress by guessing/enumerating a run id | `test_ws_channel_access_allows_owner_and_denies_stranger` |

121 tests total (30 Phase 1 + 15 Phase 2 + 30 Phase 3 + 18 Phase 4 + 15
Phase 5 + 13 Phase 6), all passing against a real `dart_test` Postgres
database. `_run_bridge` and `_check_channel_access` are both exercised
by calling them directly, the same pattern Phase 5 established for
`_run_import` — no live worker or live socket needed to test the real
logic; the live-worker path is independently verified via Postman/
Newman (see below), which is exactly where the SQLAlchemy bulk-update
bug above was caught.

## Known gaps — explicit, not accidental (Phase 7+ / future work)

- **No cross-app matching/join is computed or persisted.** Phase 6
  resolves and flags *individual* rows; it does not pair an App1 row
  with an App2 row that shares the same resolved dimension values. The
  old backend's `run_bridge`/`create_bridge` does appear to compute
  such a joined view (`get_bridge_data`), but building and persisting
  matched-pair storage is a large enough decision (what identifies a
  "match" when duplicates share a key? how are many-to-one matches
  handled?) that it's scoped to wherever the recon actually reconciles
  amounts — almost certainly Phase 7 (Transformation), which is where
  the old backend's own naming draws the line between "prepare the
  data" and "reconcile it." Not solved here on a guess.
- **`flip_sign` is stored and returned but not applied anywhere yet.**
  It's a real old-backend field (a mapping can flag that its value's
  sign should invert during reconciliation) with no reconciliation
  logic in this phase to apply it to — Phase 7's job.
- **No bridge-mapping export endpoint.** Import exists; export (for a
  round-trip edit-offline-reimport workflow) wasn't built this phase —
  the CSV column format is documented and stable, so adding it later
  is a small, independent addition.
- **The reference frontend's Bridge Members page
  (`bridge-members-panel.tsx` and `src/features/recon-pipeline/api/
  *bridge*`) is NOT rewired to the new backend** — same scoping
  precedent as Phase 3-5: backend, tests, and Postman collection
  complete; frontend rewrite is a separate, appropriately-sized
  follow-up. Worth noting explicitly: the *current* frontend page is
  itself already scoped down from the old backend's full surface (no
  inline kickout resolution UI, no bridged-data tab) — this backend
  supports more than the existing frontend page currently exercises,
  same situation as every prior phase.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # applies Phase 1-6 migrations
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload     # API (also serves /ws/{channel})
uv run celery -A app.tasks.celery_app worker --pool=solo --loglevel=info  # worker
uv run pytest                             # 121 tests total, real dart_test Postgres, no mocks
```

## Postman collection

`postman/DART_Backend_Phase6.postman_collection.json`, same environment
file as Phase 1-5, plus a checked-in fixture
(`postman/fixtures/bridge_import.csv`) for the Run Import step this
collection's setup depends on. **Requires a running Celery worker**,
same as Phase 5 — both the "Poll import run until completed" and "Poll
bridge run until completed" requests retry up to 20 times (3s apart),
since a real worker's processing time is genuinely variable. Verified
via Newman against a live server and a live worker: 28/28 requests,
35/35 assertions passing. (An earlier run caught a real sequencing bug
in the collection itself, not the API: the first version of the Setup
folder uploaded a file and moved straight to `default_bridge_mappings`
without waiting for the async import to actually finish, so it queried
zero imported rows — fixed by adding the same poll-until-completed
step Run Import's own upload flow needs.)

```bash
cd Backend/postman
npx newman run DART_Backend_Phase6.postman_collection.json \
  --environment DART_Backend_Local.postman_environment.json
```

## Extending this (Phase 7+)

**Transformation (Phase 7)** is where cross-app matching/reconciliation
almost certainly belongs — it has everything it needs from this phase:
`ImportedRow.kickout` (rows to exclude from matching), `BridgeMapping`
(the crosswalk to resolve values through, exposed via `bridge-data`'s
`resolved` field), and `flip_sign` (waiting to be applied). Design the
match-key/duplicate-handling semantics deliberately there rather than
retrofitting them onto Bridge Members.

**Any future Celery task** must use `celery_session_scope()`, never
`session_scope()` directly — see Phase 5's KT. **Any future WebSocket
job channel** should follow `bridge_run:`'s pattern in
`app/ws/router.py`'s `_check_channel_access` — check real ownership,
don't rely on channel-name obscurity.
