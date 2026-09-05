# API Build Plan — Old Backend Analysis & Phased Rebuild

Full end-to-end analysis of the old Django backend
(`C:\Users\KannanSubramaniyan\Dart\backend\Data_Recon_Backend`), done to
ground the new FastAPI build in what actually exists today rather than
guesswork. Read `../architecture.md` (the target architecture) first if
you haven't — this doc is "what to build," that one is "what stack to
build it with."

## TL;DR — where to start

**Phase 1: Identity & Auth.** Everything else — recon access, group
membership, every pipeline stage — depends on a real user/role model and
a real permission check. Build that first, or every later phase has
nothing to check permissions against. See "Recommended build order"
below for the full phase list and exactly which files to create.

## 1. The old backend's full URL surface

Root `Data_Recon_Main/Data_Recon_Main/urls.py` mounts 15 Django apps.
Cross-referenced against what the current frontend (`src/features/*/api/*.ts`)
actually calls — **zero mismatches found**; the frontend is a strict
subset of the backend's surface, nothing it calls is missing or renamed.

| Prefix | App | Used by current frontend? |
|---|---|---|
| `recon/` | `Select` | **Yes** — recon CRUD/list |
| `recon_security/` | `recon_security` | **Yes** — auth, LOB/Team/Group/Role, audit |
| `dim_linking/` | `dim_linking` | **Yes** — dimension linking stage |
| `bridge/` | `bridge_members` | **Yes** — bridge members stage |
| `run_import/` | `run_import` | **Yes** — file import stage |
| `transformation/` | `transformation` | **Yes** — transformation stage |
| `recon_meta/` | `transformation` (2nd mount, same app) | No — likely dead |
| `report/` | `run_report` | **Yes** — run report stage |
| `manage/` | `manage_users` | **Yes** — Manage Users |
| `logs/` | `Logentries` | **Yes** — Maintenance page |
| `global_variable/` | `global_variable` | No — unbuilt in new UI |
| `report_test/` | `pivot_table` | No |
| `scheduler/` | `Recon_Scheduler` (talks to Airflow directly) | No — matches Workflow Scheduler stub |
| `ai/` | `ai_proxy` (proxies to AI Auto Draft service) | No — matches AI Auto Draft stub |
| `ask_dart/` | `ask_dart` | No — matches sidebar "Ask DART" |
| `external_source/` | `external_source` | No — unbuilt in new UI |

## 2. How every endpoint actually works (the pattern to leave behind)

Every view: thin `async def` → builds `log_context` → delegates to a
`functions/*.py` module → builds `{"req_type": ..., "req_auth": user,
"req_body": {...}}` → `execute_update_query_async(payload, debug_flag)` →
unpacks `[resp_status, resp_data]` → `resp_status == 'Completed'` maps to
`{status:200}`, anything else to `{status:500, message: resp_data}`.

Two dispatch shapes:
- **Writes** — one `req_type` per operation family, often overloaded to
  handle create/update/delete via a flag in `req_body` (e.g. `create_group`
  handles create/delete/rename in one req_type via `req_actn:'a'|'d'` and
  old/new name fields). **The new backend should NOT copy this** — use
  real REST verbs (`POST`/`PATCH`/`DELETE`) instead of one endpoint that
  branches on a flag.
- **Reads** — a single generic `req_type: "fetch_data"` (99 call sites),
  differentiated by `req_body.subject_area` + `req_body.fetch_data` (query
  name) + `req_body.filter` (a WHERE-equivalent dict). This is a
  hand-rolled query DSL living entirely inside the stored procedure —
  **65 distinct query names** exist. The new backend replaces each of
  these with a real, typed endpoint (or a small set of parameterized
  list endpoints), not a generic dispatcher.

### Full write-side `req_type` catalog (49 values)
```
modify_recon  drop_recon  modify_users_in_recons  create_user  create_group
create_lob  create_team  create_role  modify_admin_group  modify_admin_lob
modify_admin_team  modify_member_group  modify_member_lob  modify_member_team
modify_lob_group  modify_team_group  modify_role_group  assign_admin_role
assign_member_role  modify_audit_status  modify_sso_provider  auth_user
auth_sso_user  modify_recon_dimension  modify_recon_transformation
modify_recon_tfn_override  modify_recon_bridge  update_recon_variance
modify_recon_signoff  modify_recon_setting  modify_recon_pivot
modify_report_filter  modify_global_variable  create_report  create_view
create_table  create_bridge  create_tfn  alter_table  load_table
import_recon  export_recon  import_gbl_var  export_gbl_var  archive_rec_gv
import_file  recongv_attach_detach  default_bridge  common_dim_name_update
ask_dart_chat  api_log
```

### Full read-side `fetch_data` query-name catalog (65 values), by area
- **Recon core**: `active_recon`, `recon_id`, `recon_app`, `recon_bridge_mapping`, `recon_dimension`, `recon_tfn`, `recon_tfn_override`, `recon_pivot`, `recon_globalvar_attach`, `possible_combinations`
- **Access/security**: `user_recon_access`, `user_privileges`, `user_unique_id`, `group_user_role`, `group_recon_role`, `recon_user_priv`, `grp_owner_priv`, `team_admin_priv`, `group_admin`, `group_member`, `group_team`, `group_team_member`, `group_lob`, `group_lob_member`, `lob_admin`, `lob_member`, `lob_team_admin`, `team_admin`, `team_member`, `list_lobs`, `list_teams`, `list_groups`, `list_roles`
- **Bridge**: `bridge`, `bridgesync_values`, `bridge_file_upload`
- **Transformation**: `transform`, `app`
- **Reports**: `report`, `report_variance`, `report_sample`, `report_filter`, `change_history`
- **Users**: `registered_users`, `non_registered_users`
- **Audit/logs**: `audit_logs`, `sso_audit_log`, `user_log`, `error_log`, `db_log`, `logs`, `check_table`
- **Global variable**: `global_variable`, `gv_app`, `gv_dimension`, `gv_tfn`, `gv_tfn_override`, `gv_bridge_mapping`
- **SSO**: `get_sso_providers`, `get_sso_provider_config`, `view_token_session`, `tkn`
- **Uploads**: `app_file_upload`

## 3. Domain model (inferred — no `sp_master` source access)

```
LOB ("Department" in the new UI)  →  Team  →  Group  →  Recon (via recon_group_xref)
                                               ↑
                                             Role (assigned per-user, per-group)
```

- **Recon** — `Recon Name`, `Recon Description`, `Group Name`, `Recon Owner`,
  `Status`, `Last Modified Date`, `Archived` (field names confirmed against
  the frontend's `list-my-recons.ts` earlier this session). Plus:
  dimensions, bridge mappings, transformation rules/overrides, pivot
  config, report filters, sign-off state, a recurring `req_level`
  scope-discriminator field (constant `"recon"` almost everywhere — shared
  with `global_variable`, which reuses `dim_linking`'s urls.py).
- **User** — email, username, hashed password, role(s) array, `group_owner`
  flag, `recon_user` flag, `audit_status`. No visibility into the real
  table — only `sp_master` ever touches it.
- **LOB / Team / Group** — name, admins (M2M), members (M2M); Group
  additionally links to Recons (`recon_group_xref` — the table whose
  missing rows caused the delete-block bug fixed earlier this session) and
  Roles.
- **Role** — name + privilege set (`delete_recon`, `update_recon`,
  `access_recon`, etc. — confirmed live via `f_validate_access` tracing
  earlier this session).
- **Dimension** — belongs to a recon, has ordering, import/export support.
- **Bridge Member / Kickout** — mapping table between two recons' dimension
  values, plus a separate "kickouts" (unmatched) sub-resource, plus JE
  comments as a further sub-resource.
- **Transformation Rule + Override** — sync-map based, per-recon and
  per-recon-override variants.
- **Report / Report Filter** — variance data, drill-down, sign-off, a
  filter sub-resource with its own CRUD and member list.
- **Audit Log** — three flavors, matching the new `AuditLogs` page's three
  tabs exactly: account-level toggle history, admin-entity change history,
  per-recon change history.
- **System/User Log** — `user_log` vs. broader `all_logs` vs.
  `error_log`/`db_log` (the latter two are commented out even in the old
  backend's `urls.py` — never wired up).
- **Global Variable** — a parallel concept to Recon, same shape, not
  surfaced in the new frontend at all yet.

## 4. Auth / permission model — and two real security bugs to not repeat

- **Login hashing bug (do not carry forward)**: the old backend hashes
  passwords with Django's `make_password(password, salt='dart')` — **a
  static, hardcoded salt shared by every single user**, which defeats
  salting's entire purpose (enables rainbow-table precomputation across
  the whole user base). The new backend's `app/core/security.py` already
  does this correctly (Argon2 via passlib, real per-hash random salt) —
  Phase 1 just needs to wire in a real user lookup, the hashing itself is
  already right.
- **Password check lives inside the SP**, not in Python — another
  instance of business logic hidden where it can't be tested, consistent
  with the delete-bug pattern already found this session.
- **JWT minting** happens in Django (`rest_framework_simplejwt`), not the
  SP: claims are `email`, `user` (username), `role` (array) — matches
  `mint_token.py`'s output shape already used all session for live testing.
- **Login response shape**: `{status, message, data: {email, username,
  role, group_owner, recon_user, accessToken, refreshToken, audit_status}}`.
  The frontend's `login-request.ts` only reads `email`/`username`/`role`/
  `accessToken`/`refreshToken` — `group_owner`/`recon_user`/`audit_status`
  are sent but currently unused (available for later, not a mismatch).
- **Authorization** (fully reverse-engineered earlier this session):
  `f_validate_access` inside `sp_master` joins
  `recon_admin.vw_usr_rcn_grp_details` (user↔group↔recon) against
  `recon_admin.vw_usr_type_access` (role↔privilege) by privilege name, and
  requires the target recon to have ≥1 row in `recon_admin.recon_group_xref`
  — zero group links means the check fails for every user unconditionally
  (confirmed root cause of a bug already fixed this session). **This exact
  join is what Phase 1's `require_privilege()` dependency replaces** — as
  explicit, testable Python against real SQLAlchemy models instead of an
  opaque PL/pgSQL view join.

## 5. Frontend ↔ backend cross-reference

Every one of the ~50 endpoints the frontend calls resolves to a real
Django view — no broken/missing routes. **Not** called by the frontend
(confirms these are deferred features or unused backend surface):
`recon/delete` (hard-delete path — already confirmed broken + unused this
session; the UI's delete button uses `recon/create` with `is_deleted:true`
instead), `recon/replicate`, `recon/archive`, all of `global_variable/*`,
`ask_dart/*`, `scheduler/*`, `ai/*`, `external_source/*`, `report_test/*`,
most SSO endpoints, several admin-listing variants, bridge's
run/export/kickout-export/je-comment endpoints, transformation's
list/override-list/export/possible-combinations, report's
signoff/export/drill-down/filter-CRUD.

## 6. Recommended build order

Identity first (everything else checks permissions against it), Recon
core next (Security's Group↔Recon link and every pipeline stage need a
real recon to point at), Security before pipeline stages (dimension/
bridge/transformation/report all sit *inside* an already-access-checked
recon).

### Phase 1 — Identity & Auth
*Replaces `recon_security/auth_user`, `f_validate_access`.*
- `app/models/user.py` — User (real Argon2 hash, no shared salt)
- `app/models/security.py` — Lob, Team, Group, Role + junction tables
  (`user_group_membership`, `group_role`, `lob_team`, `team_group`)
- `app/schemas/auth.py`, `app/schemas/user.py`
- `app/api/v1/endpoints/auth.py` — replace the current fake `/auth/token`
  scaffolding with a real check against the User model
- `app/api/deps.py` — extend `get_current_user` with a real DB lookup +
  role/scope population
- A `require_privilege(name)` dependency factory (replaces `f_validate_access`)

### Phase 2 — Recon Core
*Replaces the `Select` app.*
- `app/models/recon.py` — Recon (name, description, owner, status,
  archived, timestamps)
- `app/models/recon_security.py` — `recon_group_xref` junction
- `app/schemas/recon.py`
- `app/api/v1/endpoints/recon.py` — create/delete/list-own/list-access,
  using `require_privilege` from Phase 1

### Phase 3 — Recon Security management
*Replaces `recon_security`'s LOB/Team/Group/Role CRUD.*
- `app/schemas/security.py`
- `app/api/v1/endpoints/security.py` — LOB/Team/Group/Role CRUD,
  membership add/remove, group↔recon linking. Use real REST verbs, not
  the old one-req_type-with-a-flag pattern.

### Phase 4 — Pipeline stage 1: Dimension Linking
*Replaces `dim_linking`.*
- `app/models/dimension.py`
- `app/schemas/dimension.py`, `app/api/v1/endpoints/dimensions.py`

### Phase 5 — Pipeline stage 2: Run Import
*Replaces `run_import`.*
- `app/models/import_run.py`
- File upload → first real use of Celery (chunked/background ingestion at
  ~30 lakh-record scale per `architecture.md`, not a blocking request)
- `app/tasks/import_tasks.py`, `app/api/v1/endpoints/imports.py`

### Phase 6 — Pipeline stage 3: Bridge Members
*Replaces `bridge_members`.*
- `app/models/bridge.py` (bridge members + kickouts)
- `app/api/v1/endpoints/bridge.py` — good candidate for the already-
  scaffolded WebSocket progress layer (`run_bridge` was a distinct
  long-running action in the old backend)

### Phase 7 — Pipeline stage 4: Transformation
*Replaces `transformation`.*
- `app/models/transformation.py`
- `app/api/v1/endpoints/transformation.py`

### Phase 8 — Pipeline stage 5: Run Report
*Replaces `run_report`.*
- `app/models/report.py`
- `app/api/v1/endpoints/reports.py` — sign-off logic here is the natural
  hook point for the `app/ai/` extension point later (agentic "review and
  suggest sign-off")

### Phase 9 — Cross-cutting: Audit Logs & Maintenance
*Replaces `recon_security`'s audit endpoints + `Logentries`.*
- `app/models/audit.py` — append-only, partitioned per `architecture.md`,
  not bolted onto existing tables
- `app/api/v1/endpoints/audit.py`, `app/api/v1/endpoints/maintenance_logs.py`
- Natural place to wire `app/core/logging.py` to actually populate this
  table, replacing the old backend's separate `db_userloghandler.py` /
  `req_type: api_log` path

### Explicitly deferred (no current frontend consumer)
`global_variable`, `ask_dart`, `external_source`, `pivot_table`,
`scheduler` (Airflow — `architecture.md` says keep Airflow; becomes real
work once Phase 5+ has background jobs to schedule), `ai_proxy`
(superseded by `app/ai/` once AI Auto Draft is integrated directly).
