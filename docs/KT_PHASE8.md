# KT — Phase 8: Run Report

Knowledge transfer for what was actually built, why it's shaped the way
it is, how to run/test/extend it, and what's deliberately left for
Phase 9. Companion docs: `KT_PHASE1.md` through `KT_PHASE7.md`,
`../architecture.md`, `BUILD_PLAN.md`.

## The core correction this phase made to its own starting assumption

Phase 6's KT guessed cross-app row matching belonged to Phase 7. Phase
7's own research corrected that to "not Phase 7 either — check Phase 8's
`run_rprt.py` directly." That third look confirmed it: matching,
variance computation, and sign-off all live in the old backend's
`run_report` app, but **the actual computation is not readable Python
anywhere in that repository.** `run_rprt.py` (`Data_Recon_Backend/
.../run_report/functions/run_rprt.py`) delegates every real step —
`create_report`, `fetch_data` — to a stored procedure (`sp_master`)
reached through `execute_update_query_async`/`execute_fetch_query_async`.
This is the same situation Phase 5 (import column parsing) and Phase 6
(bridge CSV column format) already found and resolved the same way:
**define a clean, explicit contract here and document it as a decision**
rather than reverse-engineer opaque SQL. See `app/api/v1/endpoints/
report_data.py`'s module docstring for the itemized list of what's
ported faithfully (readable) vs. new-backend-defined (not readable).

## What's here

| Table | File | Purpose |
|---|---|---|
| `report_signoffs` | `app/models/report.py` | Per-`(recon, app_number)` sign-off boolean + who/when |
| `report_filters` | `app/models/report.py` | Named, saved `{dimension_name: [allowed values]}` criteria |

| Module | File | Purpose |
|---|---|---|
| Report computation | `app/api/v1/endpoints/report_data.py` | `run`, `export`, `drill-down`, `last-refresh`, `signoff` (GET/POST) |
| Report filters | `app/api/v1/endpoints/report_filters.py` | CRUD + `/members` (distinct dimension values for a filter-builder UI) |

No report row or variance figure is persisted anywhere — same "computed
at read time" precedent as Bridge's `resolved` field and Sync's
`synced` field. The only Phase 8 state that IS persisted is sign-off
(a real user decision, not a derived value) and saved filters (named
user configuration, also not derived).

## Why it's shaped this way

**Matching happens on bridge-resolved values, not raw ones.** Every
non-`AMOUNT` dimension on a row is resolved through `BridgeMapping`
(app_number, dimension_name, raw value) → canonical value before the
match key is built; a dimension value with no mapping falls back to its
raw value unchanged. This is the first phase that actually depends on
Phase 6's own stated design intent — its docstring says bridge mappings
normalize a value "*before* any cross-system matching happens" — being
true, not just aspirational.

**The variance formula is new-backend-defined:**
`variance = app1_amount - app2_amount` (signed — a caller can tell which
side is higher), where each app's amount is the sum of `AMOUNT` across
that app's rows sharing a resolved match key, negated per-row if that
row's key was built using any `BridgeMapping` with `flip_sign=True`.
This closes the "`flip_sign` is stored but not applied" gap Phase 6 and
Phase 7's KTs both flagged and deferred here — but only for
`BridgeMapping.flip_sign`. **`SyncMapping.flip_sign` is deliberately
NOT applied** — sync mappings rewrite a display value tied to one
specific source value, they don't participate in matching or amount
computation, and inventing a rule for how they'd affect a sign here
would be exactly the kind of unguided guess this project has
consistently avoided. It remains an explicit, still-open gap (below),
not a silently dropped one.

**`variance_threshold` is a request-time parameter (default `0`), not a
stored per-recon config file.** The old backend reads a flat
`Recon_name_variance_threshold.json` matched by a `{recon_name}_` string
key prefix — global mutable file state on disk, exactly the pattern
this project has moved away from at every prior phase (JSONB columns
instead of dynamic DDL, upsert tables instead of stored procedures).
Making it a call-time parameter is strictly more flexible (a caller can
try several thresholds without a config write) at the cost of the old
behavior's "sticky" default — a real trade-off, made explicitly rather
than ported blindly.

**Rows with `ImportedRow.kickout=True` are excluded from the report
entirely**, not shown as a third bucket. A kickout row is one Bridge
Members couldn't resolve — showing it in a reconciliation report either
matched or unmatched would misrepresent it as "compared" when it's
actually "not ready to compare yet." `bridge-data`'s own kickout filter
(Phase 6) is where those rows already belong for triage.

**A row's `app1_data`/`app2_data` is the last-seen row's raw JSONB for
that match key, and its amount is the *sum* across every row sharing
that key on that app** — the old backend's own report is a many-to-many
aggregate (grouped by dimension combination, not by individual row id),
confirmed by the shape of `all_report_original_var.py`'s per-key
variance-count loop operating over already-grouped `resp_data`. If two
rows in the same app happen to land on the same resolved key,
their amounts are summed and only one's raw data is kept as a
representative sample — documented here rather than silently assumed,
since it's the one place duplicate keys within a single app could
surprise a reader expecting one-row-per-key.

**Saved filters apply an IN-filter against each app's *raw* dimension
value, independently per app**, not against the resolved match key.
`criteria: {"ACCOUNT": ["ACCT_A", "ACCT_A_ALT"]}` includes App1 rows
whose raw `ACCOUNT` is `ACCT_A` *and* App2 rows whose raw `ACCOUNT` is
`ACCT_A_ALT` — the caller supplies both apps' raw spellings for what
is, after bridging, the same canonical value. This mirrors the old
backend's own "original vs. filtered" split (`run_rprt.py`'s explicit
merge of the two), reimplemented as a single computation invoked twice
with different row sets (`filter_id` present or absent) rather than two
separate response shapes.

**Sign-off is an upsert (`INSERT ... ON CONFLICT DO UPDATE`) keyed by
`(recon_id, app_number)`**, matching `rcn_signoff.py`'s own semantics of
calling `modify_recon_signoff` once per `app_type` in the request body
— a real state transition (who signed off, when), not a derived value,
so it's the one piece of Phase 8 state that's actually written to a
table rather than computed on read.

**Route order**: `/members` is registered before `/{filter_id}` in
`report_filters.py` — the same literal-before-parameterized rule every
prior phase has needed, applied proactively.

## Security properties (each has a test)

| Property | Why | Test |
|---|---|---|
| Every route requires authentication and recon ownership | Same shared `get_accessible_recon` as every prior phase | `test_non_owner_cannot_run_or_signoff_report` |
| Matching uses bridge-resolved values, not raw ones | The whole point of normalizing before comparing | `test_run_report_matches_via_bridge_resolved_key` |
| `variance_threshold` actually suppresses sub-threshold differences | Otherwise it's a documented parameter that does nothing | `test_variance_threshold_suppresses_small_differences` |
| `BridgeMapping.flip_sign` negates a matched row's amount | Closes the gap Phase 6/7 both flagged and deferred | `test_flip_sign_negates_matched_amount` |
| Kickout rows never appear in the report | Misrepresenting an unresolved row as compared would be worse than omitting it | `test_kickout_rows_are_excluded_from_report` |
| AMOUNT never appears as a match-key dimension | It's the measure, not a matching key — same exclusion as every prior phase | Asserted inline in `test_run_report_matches_via_bridge_resolved_key` |
| A saved filter narrows both apps' raw values independently | The "original vs filtered" distinction actually changes the result | `test_report_filter_narrows_matching_rows` |
| Duplicate filter name per recon is rejected | Prevents ambiguous "which filter wins" by name | `test_duplicate_filter_name_is_conflict` |
| Sign-off upserts per app, doesn't create duplicate rows | `uq_report_signoff_recon_app` + `ON CONFLICT DO UPDATE` | `test_signoff_upserts_per_app` |

142 tests total (30 Phase 1 + 15 Phase 2 + 30 Phase 3 + 18 Phase 4 + 15
Phase 5 + 13 Phase 6 + 9 Phase 7 + 12 Phase 8), all passing against a
real `dart_test` Postgres database, mypy-clean, ruff-clean. The kickout
test calls `_run_bridge` directly (same pattern Phase 6/7 established
for `_run_import`) — no live worker needed to test the real matching
logic; the live-worker path (imports only — `report/run` itself needs
no worker, it's synchronous) is independently verified via Postman/
Newman below.

## Known gaps — explicit, not accidental (Phase 9+ / future work)

- **`SyncMapping.flip_sign` still is not applied anywhere.** As
  detailed above, applying it here would require inventing semantics
  Phase 7 never defined (sync mappings aren't part of matching). If a
  future phase needs it, design that deliberately rather than
  retrofitting it onto this phase's amount computation.
- **No "card report" (`all_report=false`) equivalent.** The old
  backend's own `run_rprt.py` comment notes the card view isn't a real
  table in the current DART frontend — same precedent as Phase 6/7 not
  building unused surface. If a card/summary view is needed later, it's
  a small aggregation over `run_report`'s existing per-row output, not
  a parallel implementation.
- **No archive endpoint** (`archieved_files` in the old backend's
  `urls.py`). Nothing readable in this codebase's `run_report/functions/`
  defines what "archived" means distinctly from "an old `ImportRun`,"
  which Phase 5's `imports` list endpoint already exposes — not solved
  here on a guess rather than a confirmed distinct concept.
- **No `filter_export`/CSV round-trip for saved filters themselves**
  (distinct from the report `export`, which does exist). Not found as a
  clearly separate old-backend surface during this phase's research —
  a small, independent addition if a future phase needs it.
- **The reference frontend has no Run Report page wired to this
  backend** — same scoping precedent as every prior phase: backend,
  tests, and Postman collection complete; a frontend page is a
  separate, appropriately-sized follow-up.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # applies Phase 1-8 migrations
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload     # API
uv run pytest                             # 142 tests total, real dart_test Postgres, no mocks
```

No Celery worker is needed to exercise Phase 8's own endpoints
(`report/run`, `signoff`, filters are all synchronous) — a worker is
only needed for the Postman collection's Setup folder, which depends on
two Run Imports the same way Phase 6/7's collections do.

## Postman collection

`postman/DART_Backend_Phase8.postman_collection.json`, same environment
file as Phase 1-7, plus two checked-in fixtures (`postman/fixtures/
report_app1.csv`, `report_app2.csv`) whose `ACCT_A`/`ACCT_A_ALT` values
exercise the bridge-resolved matching this phase's whole design depends
on. **Requires a running Celery worker** for the two Run Import steps
only — `report/run` and everything else in this collection is
synchronous. Verified via Newman against a live server and a live
worker: 31/31 requests, 35/35 assertions passing on first real run.

```bash
cd Backend/postman
npx newman run DART_Backend_Phase8.postman_collection.json \
  --environment DART_Backend_Local.postman_environment.json
```

## Extending this (Phase 9)

**Audit Logs & Maintenance (Phase 9)** doesn't depend on this phase's
computation, but sign-off (a real, auditable state change written by
this phase) is exactly the kind of event an audit trail should capture
— when Phase 9's audit log lands, add a `report_signoff` event type
alongside whatever else it tracks, rather than inventing a separate
history mechanism just for sign-off.

**If `SyncMapping.flip_sign` semantics get defined later**, the
integration point is `_compute_report`'s `resolve_key_and_sign` closure
in `report_data.py` — it already carries a `flip` bool per row from
`BridgeMapping`; a second, independently-computed flip from
`SyncMapping` would OR into the same variable, not require restructuring
the grouping logic.
