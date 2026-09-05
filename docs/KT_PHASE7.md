# KT — Phase 7: Transformation (Sync Mapping)

Knowledge transfer for what was actually built, why it's shaped the way
it is, how to run/test/extend it, and what's deliberately left for
Phase 8+. Companion docs: `KT_PHASE1.md` through `KT_PHASE6.md`,
`../architecture.md`, `BUILD_PLAN.md`.

## The core correction this phase made to its own starting assumption

Phase 6's KT flagged cross-app matching/reconciliation as "almost
certainly Phase 7's job." That guess was checked against the old
backend's actual source before any code was written, and it was wrong
in a specific way: Phase 7 isn't cross-app row matching at all — it's a
**value crosswalk**, structurally similar to Phase 6's `BridgeMapping`
but serving a different purpose. A `sync_mappings` entry is
`(recon, app_number, dimension_names[], concat_delimiter, source_sync) →
target_sync`: it rewrites one app's raw dimension value (or a
delimiter-joined *composite* of several dimensions' values) to a target
value, computed fresh against imported rows on read. There is still no
persisted cross-app pairing anywhere in this codebase — that remains
out of scope, now explicitly reassigned to Phase 8 (Run Report) below,
which is where the old backend's own module boundary actually draws
the "reconcile it" line (`run_rprt.py`, not anything in
`transformation`/`sync`).

## What's here

| Table | File | Purpose |
|---|---|---|
| `sync_mappings` | `app/models/sync.py` | The crosswalk: `(recon, app_number, dimension_names[], concat_delimiter, source_sync) → target_sync` |

| Module | File | Purpose |
|---|---|---|
| Mapping CRUD | `app/api/v1/endpoints/sync_mappings.py` | Create/list/update/delete, `/possible-combinations` |
| Sync data | `app/api/v1/endpoints/sync_data.py` | Read-back: `POST .../sync-data/run`, resolved values computed at read time |

## Why it's shaped this way

**`SyncMapping` is a separate table from `BridgeMapping`, deliberately
not unified, despite being structurally close (source→target,
`flip_sign`).** This is a considered rejection of unification, not an
oversight — contrast with Phase 1's precedent of collapsing six
near-identical membership tables into one. That precedent doesn't apply
here because the two tables' *purposes* differ, not just their shape:
`BridgeMapping` normalizes a single raw value to a canonical identity
*before* matching (kickout detection is its whole point — a value with
no crosswalk entry is unresolved and flagged); `SyncMapping` rewrites a
resolved value (or composite of several) to a *final* value for the
report, with no kickout concept at all — every unmapped row simply
carries an empty `synced` dict, not an error state. `BridgeMapping` was
also already shipped and tested by the time Phase 7 started; changing
its shape to accommodate this second purpose would have been scope
creep in the wrong direction.

**`dimension_names` is an array, not a single column, because a sync
mapping can key off a *composite* of several dimensions' values, joined
by a configurable delimiter.** Confirmed against the old backend's
`generate_comb.py`/`create_tfn` naming and column handling — a single
sync mapping row can represent e.g. `ACCOUNT|COST_CENTER` jointly
mapping to one target value, not just one dimension at a time the way
`BridgeMapping` is. `concat_delimiter` defaults to `-` but is
per-mapping configurable (tested with `|` to make sure it's not
hardcoded).

**`possible-combinations` uses `zip(*value_lists)`, not
`itertools.product`.** This was the single most surprising thing found
while reading `generate_comb.py` directly — the intuitive reading of
"give me candidate combinations of these dimensions' distinct values"
is the cross product, but the old backend's actual implementation pairs
each dimension's distinct-value list *positionally*. Two dimensions
with 2 distinct values each yields 2 candidate combinations, not 4.
This only makes sense when the dimensions are already row-aligned in
the source file (which they are, since both lists come from the same
`ImportedRow.data` rows) — but it's what's there, so it's what's
replicated, with an explicit test (`test_possible_combinations_zips_not_products`)
asserting the count specifically to catch a future "helpful" switch to
`itertools.product`. Each dimension's distinct-value list is sorted
here for determinism; the old backend's own ordering (live scan order
from its stored procedure) isn't reproducible or meaningful outside
that context — a repeat of the same call made in Phase 6 for its
default-mapping ordering.

**`run_transformation` (`sync-data/run`) has no Celery task — a
deliberate difference from Bridge's `run_bridge` (Phase 6), not an
oversight.** Bridge's task exists because it writes a real side effect
back to storage (`ImportedRow.kickout`). Transformation has no
equivalent: resolving a row's synced values is a pure computed join
between `ImportedRow.data` and `SyncMapping`, same shape as Bridge's
own `resolved` field in `bridge-data`, which is also computed on read,
not written back. Nothing here needs a background job or a stored
result — if per-row compute cost at scale later proves otherwise, that
is a mechanical change (wrap the same function in a Celery task,
`bridge_tasks.py`'s shape), not a redesign. Documented at the top of
`sync_data.py` itself so the "why no task" question doesn't have to be
re-litigated by grepping for one.

**When multiple mappings resolve the same row, later table-order
mappings simply overwrite earlier ones in the returned `synced` dict** —
`_resolve` iterates `mappings` in the order they were queried
(`SyncMapping.recon_id == recon_id`, no explicit `ORDER BY` beyond
what `list_sync_mappings` applies for its own listing) and each
matching mapping's `group_key` (dimensions joined by `-`) is a distinct
dict key, so a simple-dimension mapping (`ACCOUNT`) and a composite
mapping (`ACCOUNT-COST_CENTER`) on the same row coexist rather than
collide — confirmed by the Postman collection's "Run transformation"
request, which asserts both keys are present on the same row
simultaneously (see below). Two mappings with the *identical*
`dimension_names` set can't coexist in the first place: the
`uq_sync_mapping_key` constraint on `(recon_id, app_number,
dimension_names, source_sync)` prevents a true collision at write time.

**AMOUNT exclusion is enforced the same way as Phase 6.** It's the
measure being reconciled, not a matching/lookup key — same
`_SYNC_DIMENSION_EXCLUDE` pattern (a set literal, not a config value)
as `bridge_mappings.py`'s `_BRIDGE_DIMENSION_EXCLUDE`, confirmed against
the same old-backend hardcoded filters Phase 6 found.

**Route order**: `/possible-combinations` is registered before
`/{mapping_id}` in `sync_mappings.py` — the same literal-before-
parameterized rule every prior phase has needed, applied proactively
this time rather than discovered by a live 422.

## Security properties (each has a test)

| Property | Why | Test |
|---|---|---|
| Every route requires authentication and recon ownership | Same shared `get_accessible_recon` as every prior phase | `test_non_owner_cannot_manage_sync_mappings` |
| AMOUNT cannot be sync-mapped | It's the measure, not a matching/lookup key — enforced server-side | `test_amount_cannot_be_sync_mapped` |
| A duplicate `(app_number, dimension_names, source_sync)` key is rejected | Prevents ambiguous "which target wins" mappings | `test_duplicate_sync_mapping_key_is_conflict` |
| `dimension_names` cannot contain blank entries | Schema-level validation, not just a downstream KeyError | Covered by `SyncMappingCreate._no_blank_names`, exercised implicitly by every create test |
| `possible-combinations` returns row-positional pairs (zip), not the cross product | The single most surprising design decision this phase found — an easy thing to "fix" wrongly later | `test_possible_combinations_zips_not_products` |
| A simple mapping and a composite mapping both resolve independently on the same row | `_resolve`'s per-mapping `group_key` design | `test_run_transformation_resolves_synced_values`, `test_run_transformation_resolves_concat_mapping` |
| A row with no matching mapping returns an empty `synced` dict, not an error | No kickout concept here — unmapped is a normal, expected state | `test_run_transformation_resolves_synced_values` (asserts `unmapped_row["synced"] == {}`) |

130 tests total (30 Phase 1 + 15 Phase 2 + 30 Phase 3 + 18 Phase 4 + 15
Phase 5 + 13 Phase 6 + 9 Phase 7), all passing against a real
`dart_test` Postgres database, mypy-clean, ruff-clean. `run_transformation`
is exercised via the real HTTP client + a real completed import (via
`_run_import` called directly, same pattern as Phase 6), no mocks.

## Known gaps — explicit, not accidental (Phase 8+ / future work)

- **No cross-app row matching/pairing is computed or persisted here
  either** — that responsibility has now been checked against the old
  backend twice (once wrongly assigned to Phase 6, corrected to "maybe
  Phase 7" in that KT, now confirmed *not* Phase 7 either) and belongs
  to Phase 8 (Run Report), which is where `run_rprt.py` actually lives
  in the old backend. Not solved here on a second guess — Phase 8's
  own research will read `run_rprt.py` directly before committing to a
  design, same discipline as every prior phase.
- **`flip_sign` is stored and returned on `SyncMapping` but still not
  applied anywhere** — same gap Phase 6's KT noted for `BridgeMapping`'s
  own `flip_sign`. Both are waiting on Phase 8's reconciliation/report
  computation, which is presumably where a value's sign actually
  matters for amount comparison.
- **No sync-mapping CSV import/export**, unlike Bridge's `/import`
  (Phase 6). Not found as a distinct old-backend surface during this
  phase's research the way bridge import was — if a future phase finds
  one, it's a small, independent addition following Bridge's CSV
  pattern.
- **The reference frontend has no Sync/Transformation page to rewire** —
  same scoping precedent as every prior phase: backend, tests, and
  Postman collection complete; a frontend page (if/when designed) is a
  separate, appropriately-sized follow-up.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # applies Phase 1-7 migrations
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload     # API
uv run pytest                             # 130 tests total, real dart_test Postgres, no mocks
```

No Celery worker is needed to exercise Phase 7's own endpoints (`sync-data/run`
is synchronous) — a worker is only needed for the Postman collection's
Setup folder, which depends on Run Import (Phase 5) the same way
Phase 6's collection does.

## Postman collection

`postman/DART_Backend_Phase7.postman_collection.json`, same environment
file as Phase 1-6, plus a checked-in fixture
(`postman/fixtures/sync_import.csv`, two rows across `YEAR, ACCOUNT,
COST_CENTER, AMOUNT`) for the Run Import step this collection's setup
depends on. **Requires a running Celery worker** for that setup step
only, same as Phase 5/6 — "Poll import run until completed" retries up
to 20 times (3s apart). Verified via Newman against a live server and a
live worker: 24/24 requests, 32/32 assertions passing on first real
run — no bugs found in this phase's live verification (unlike Phase 6's
sequencing bug), likely because the Setup folder's poll-before-proceed
pattern was already established and copied forward rather than
reinvented.

```bash
cd Backend/postman
npx newman run DART_Backend_Phase7.postman_collection.json \
  --environment DART_Backend_Local.postman_environment.json
```

## Extending this (Phase 8+)

**Run Report (Phase 8)** is where cross-app matching, reconciliation,
sign-off, and `flip_sign` application almost certainly belong — it has
everything it needs from Phases 5-7: `ImportedRow.kickout` (rows to
exclude), `BridgeMapping`'s resolved values, and `SyncMapping`'s
resolved/synced values. Design the actual matching/variance semantics
by reading `run_rprt.py` and `rcn_signoff.py` directly before writing
any code — this phase's own correction (Phase 6's KT guessed wrong
about where matching belongs) is itself the argument for that
discipline, not a one-off.

**Any future read-heavy, no-side-effect computation** (a third
"resolve values against a mapping table" pattern, if one shows up)
should stay synchronous like `sync_data.py`, not default to a Celery
task just because Bridge and Import both use one — the task boundary
tracks "does this write a real persisted side effect," not "is this
compute-shaped work."
