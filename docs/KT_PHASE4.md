# KT — Phase 4: Dimension Linking

Knowledge transfer for what was actually built, why it's shaped the way
it is, how to run/test/extend it, and what's deliberately left for
Phase 5+. Companion docs: `KT_PHASE1.md`, `KT_PHASE2.md`, `KT_PHASE3.md`,
`../architecture.md`, `BUILD_PLAN.md`.

## What's here

| Table | File | Purpose |
|---|---|---|
| `recon_apps` | `app/models/dimension.py` | Import/parsing settings for one of a recon's (in practice, exactly two) source systems — delimiter, currency format, header row |
| `dimensions` | `app/models/dimension.py` | One common name (e.g. `AMOUNT`), ordered by `position` |
| `dimension_mappings` | `app/models/dimension.py` | Per-`(dimension, app)` row: either a file column location, or a fixed default when the value isn't in the file at all |

| Endpoint group | File | Routes |
|---|---|---|
| Recon Apps | `app/api/v1/endpoints/recon_apps.py` | `POST`/`GET /recons/{id}/apps`, `PATCH /recons/{id}/apps/{app_number}` |
| Dimensions | `app/api/v1/endpoints/dimensions.py` | `POST`/`GET /recons/{id}/dimensions`, `GET`/`PATCH`/`DELETE /recons/{id}/dimensions/{id}`, `POST .../{id}/reorder`, `POST .../seed-mandatory`, `GET .../export`, `POST .../import` |

Both routers share one access check —
`app/core/recon_access.py`'s `get_accessible_recon` — extracted from
`recons.py` this phase specifically so a newer module can't quietly
diverge from the ownership/404-not-403 rule Phase 2 established.
`recons.py` itself now calls the same shared function.

## Why it's shaped this way

**A "recon app" is settings, not a business entity.** Traced directly
in the old backend: `dim_linking/save/details` is really `modify_recon_
setting` under the hood — CSV delimiter, currency formatting, header
row. Nothing else references it as a first-class thing. Modeled here as
a plain row scoped to a recon and an `app_number` (1 or 2, enforced by a
`CHECK` constraint), not a separate aggregate.

**A dimension is one name with per-app mappings, not one row per app.**
The old backend's `dim_linking/update` sends one array entry per app in
a single call, all sharing the same `dimension_order` — confirmed this
is genuinely "one concept, two sourcings," not two independent things
that happen to share a name. `Dimension` (name + position) and
`DimensionMapping` (per-app column-or-default) reflect that split
directly; `DimensionCreate`'s schema-level validator requires exactly
one mapping for app 1 and one for app 2, so the shape can't drift from
what every real old-backend payload always was even though the old
backend itself never enforced it.

**Recon Apps and Dimensions are hard-deleted, not soft-deleted like
Recon.** They're configuration scoped to an already soft-deletable
Recon (`ondelete="CASCADE"` on the parent handles cleanup), not primary
records that need their own audit trail — a deliberate, narrower
choice than Recon's soft delete, not an inconsistency.

**Create is create-only for Recon Apps, not the old backend's
upsert-by-`(recon_name, app_type)`.** Matches every other create
endpoint already in this codebase (`create_user`, `create_recon`,
`create_lob`, ...) — one consistent rule across the whole API, not a
special case for this one entity, even though the old backend behaved
differently here.

**Reorder is implemented as remove-and-reinsert-then-renumber, not the
old backend's narrower range-shift loop.** Both produce an identical end
state for the case that matters (move one dimension, everything
strictly between its old and new position shifts by one) — the
simpler implementation was chosen because it's easier to verify
correct, not because the old behavior was misunderstood. See
`reorder_dimension`'s docstring for the two-phase (temporary-negative-
then-final) position update this requires to avoid tripping the
`uq_dimension_recon_position` unique constraint mid-update.

## Security properties (each has a test)

| Property | Why | Test |
|---|---|---|
| Every route requires authentication and recon ownership | Same rule as Phase 2's Recon endpoints, now shared code | `test_non_owner_cannot_see_or_create_recon_apps`, `test_non_owner_gets_404_not_403_for_dimensions` |
| Non-owner gets 404, never 403 | Same enumeration-resistance reasoning as every prior phase | `test_non_owner_gets_404_not_403_for_dimensions` |
| **A mandatory dimension (YEAR/PERIOD/AMOUNT) cannot be deleted through this API, on any path** | The old backend's *bulk* CSV-import delete correctly excluded these three, but its *single*-dimension delete endpoint had no such check at all — a direct API call there could delete YEAR/PERIOD/AMOUNT even though the reference frontend's UI never exposed the button. Both delete paths here (`delete_dimension`, and the bulk-replace inside `import_dimensions`) enforce the same protection — a real fix, not a port of the bug | `test_mandatory_dimension_cannot_be_deleted`, `test_import_replaces_non_mandatory_dimensions_but_keeps_mandatory` |
| A dimension mapping can't claim `in_file` without a column, or "not in file" without a default | Schema-level validation the old backend left to convention | `test_create_dimension_missing_column_location_when_in_file_is_422` |
| A dimension must map both apps, never just one | Schema-level validation, same reasoning | `test_create_dimension_requires_both_app_numbers` |
| Duplicate dimension name / app number is a clean 409, not a 500 | Same check-then-insert-with-`IntegrityError`-catch pattern as every prior phase | `test_duplicate_dimension_name_is_conflict`, `test_create_recon_app_duplicate_number_is_conflict` |
| A malformed import row aborts the whole import, not a partial write | Parsed and validated in full before any delete or insert happens | `test_import_malformed_row_aborts_without_partial_writes` |
| Reorder never produces a duplicate position, even mid-transaction | The two-phase temp-then-final update | `test_reorder_shifts_intervening_dimensions` |
| Seeding mandatory dimensions is idempotent | Safe to call more than once, doesn't duplicate | `test_seed_mandatory_dimensions_is_idempotent` |

93 tests total (30 Phase 1 + 15 Phase 2 + 30 Phase 3 + 18 Phase 4), all
passing against a real `dart_test` Postgres database.

## Known gaps — explicit, not accidental (Phase 5+ / future work)

- **The `global_variable_name` branch present in every old-backend
  `dim_linking` function was not replicated.** Every real frontend call
  sends it as `''`, and `BUILD_PLAN.md` already lists `global_variable`
  as explicitly deferred with no current frontend consumer. Replicating
  it would have roughly doubled the complexity of every endpoint here
  for a feature nothing calls.
- **Dimension rename has no side effect on physical data**, unlike the
  old backend (`alter_table` against the recon's imported-data table
  when a name changes). Irrelevant until Phase 5 (Run Import) creates
  real per-recon data tables — nothing to replicate yet.
- **No "dimensions changed, re-validate the import" signal.** The old
  backend fires `Change_updateflag_status(recon_name, "runimport")`
  after dimension updates; nothing in the new `Recon` model tracks
  per-stage staleness yet. Flagged for Phase 5's design, not solved
  here on a guess.
- **The reference frontend's Dimension Linking page (`dimension-
  linking-panel.tsx` and everything under `src/features/recon-pipeline/
  components/*dimension*`, `*recon-app*`) is NOT rewired to the new
  backend.** Only the backend, its tests, and its Postman collection are
  done this phase — matching Phase 3's precedent of shipping a complete,
  verified backend while explicitly deferring a full frontend rewrite of
  a page this size. The old backend's `dim_linking` app remains live and
  unaffected; this phase's endpoints are net-new and don't conflict with it.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # applies Phase 1-4 migrations
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload
uv run pytest                             # 93 tests total, real dart_test Postgres, no mocks
```

## Postman collection

`postman/DART_Backend_Phase4.postman_collection.json`, same environment
file as Phase 1-3. Self-contained. Verified via Newman against a live
server: 22/22 requests, 27/27 assertions passing.

```bash
npx newman run Backend/postman/DART_Backend_Phase4.postman_collection.json \
  --environment Backend/postman/DART_Backend_Local.postman_environment.json
```

## Extending this (Phase 5+)

**Wiring up the Dimension Linking frontend page:** every field the
existing `src/features/recon-pipeline/api/*dimension*`,
`*recon-app*` files expect maps directly to a route already built
here — same id-not-name shift Phase 2/3 made for Recon/Group. The CSV
import/export format (`serial_no` + 5 columns per app:
`Dimension Name_N`, `Dimension In File_N`, `Location in File_N`,
`Default Value_N`, `Active Flag_N`) is unchanged from the old backend
on purpose, so an old export file can be re-imported here without
reformatting.

**Run Import (Phase 5):** will need the "dimensions changed" staleness
signal flagged above, and is the first phase to actually parse and
store the CSV files these dimensions describe — `ReconApp`'s delimiter/
currency/header settings are exactly the config Phase 5's CSV parser
needs, already in place.
