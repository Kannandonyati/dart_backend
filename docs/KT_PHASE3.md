# KT — Phase 3: Recon Security Management

Knowledge transfer for what was actually built, why it's shaped the way
it is, how to run/test/extend it, and what's deliberately left for
Phase 4+. Companion docs: `KT_PHASE1.md`, `KT_PHASE2.md`,
`../architecture.md`, `BUILD_PLAN.md`.

## Why this phase started with a correction, not new code

Before any Phase 3 code was written, the frontend integration from
Phase 2 was challenged: does creating a recon on the old backend
actually require picking a group? Checking the old backend's source
directly (not relying on notes) confirmed it does — `get_group_names_
list.py` (groups the caller belongs to) feeds a dropdown, and
`add_grp_to_rcn.py` (`modify_users_in_recons`, `recn_actn: 'a'`) links
the new recon to the chosen group as a second call right after create.
Phase 2's frontend integration dropped this — a real regression, not a
deferred feature — because a recon deferred every "future phase" from
group management, when only the *creation dropdown* was actually
missing; group management proper genuinely is this phase.

That same re-check also caught a second, more serious problem: Phase 1
modeled `Group.team_id` as a required single foreign key. The old
backend's actual `create_group` takes only a name — no team, no lob —
and groups are linked afterward via separate `add/lob_grp` and
`add/team_grp` calls. The existing frontend's `GroupDetails` type
(`lobNames`/`teamNames`, both arrays) independently confirms this: a
group is many-to-many with both, not parented to either. Both
corrections are in this phase's migration — see "Schema changes" below.

## What's here

| Table | File | Purpose |
|---|---|---|
| `group_lobs`, `group_teams` | `app/models/security.py` | Group↔Lob and Group↔Team, many-to-many (replaces Phase 1's wrong `Group.team_id`) |
| `group_roles` | `app/models/security.py` | Role↔Group linking — old backend's `add_role_group` |
| `lobs.created_by_id`, `groups.created_by_id` | `app/models/security.py` | Who created it — the reference frontend's `Lob`/`Group` types show `createdBy` |
| `memberships.role_id` (now nullable) | `app/models/security.py` | A NULL-role row is "belongs to this scope" (old backend's plain `group_member`); a row with a role is "holds a role there" |

| Endpoint group | File | Routes |
|---|---|---|
| LOBs | `app/api/v1/endpoints/lobs.py` | CRUD + `/admins`, `/members` (add/remove/list) |
| Teams | `app/api/v1/endpoints/teams.py` | CRUD (scoped to a `lob_id`) + `/admins`, `/members` |
| Groups | `app/api/v1/endpoints/groups.py` | CRUD, `/details`, `/mine`, `/admins`, `/members`, `/lobs/{id}`, `/teams/{id}`, `/roles/{id}` (link/unlink) |
| Roles | `app/api/v1/endpoints/roles.py` | CRUD against a closed privilege catalog |
| Recon↔Group | `app/api/v1/endpoints/recons.py` | `POST`/`DELETE /recons/{id}/groups/{group_id}` — added to Phase 2's router |

## Schema changes to already-shipped Phase 1/2 tables

Both migrated with a real Alembic revision
(`4eb5fdf0f6b8_phase3_recon_security_management.py`), not a rewrite of
Phase 1/2's migrations — those already ran in real environments and
must stay replayable in order:

1. **`groups.team_id` dropped**, its unique constraint (`team_id`,
   `name`) replaced with a plain unique constraint on `name` alone, and
   `group_lobs`/`group_teams` join tables added.
2. **`memberships.role_id` changed from `NOT NULL` to nullable.** A
   plain `UniqueConstraint` treats every `NULL` as distinct from every
   other `NULL` in Postgres, so a second partial unique index
   (`uq_membership_plain`, `WHERE role_id IS NULL`) was added
   alongside the existing constraint to still prevent duplicate
   plain-member rows — the existing constraint alone would have let a
   user join the same group as a "plain member" twice.

## Why it's shaped this way

**One privilege, `security:manage`, gates every write across LOB/Team/
Group/Role.** The old backend has four real delegation tiers — account,
lob, team, group admins each manage what's under them — traced via
`req_level` in the reference frontend's API calls. Replicating that
tiered delegation faithfully is a real sub-project (it needs scope
inheritance, which Phase 1 explicitly deferred — see its KT's "Why it's
shaped this way"). Phase 3 makes the same simplification Phase 1 made
for Membership and Phase 2 made for `recon:manage_all`: one coarse
privilege, one code path, superuser bypass, extend later when a real
consumer needs finer delegation. This is a narrower surface than the
old backend on day one — documented here, not silently shipped.

**"Admin of a scope" is a label role, not a boolean column.** Whether a
user is an admin or a plain member of a Lob/Team/Group is represented
by whether their `Membership` row for that scope has the seeded
`"Admin"` role attached (`role_id` set) or not (`role_id` NULL) — reusing
the same table and the same nullable-`role_id` mechanism, rather than
adding an `is_admin` boolean to `Membership`. The `Admin` role carries
no privileges of its own; `security:manage` is still the only thing
that actually authorizes a write.

**The real 10-item privilege catalog coexists with this rebuild's own
coarse gates, rather than replacing them.** `create_recon`,
`read_recon`, `update_recon`, `delete_recon`, `execute_recon`,
`sign_off_recon`, `import_recon`, `export_recon`, `replicate_recon`,
`archive_recon` are the old backend's actual, closed privilege names
(confirmed against the reference frontend's `data.ts`, which hardcodes
exactly this list for its role-creation multi-select — not admin-
definable free text). They're seeded so Role CRUD has real values to
assign and the reference frontend's role multi-select has something
meaningful to show. They are **not** yet checked by any
`require_privilege()` call — see "Known gaps."

**A closed privilege catalog, enforced at the API, not just the UI.**
`RoleCreate`/`RoleUpdate` reject any `privilege_names` entry that isn't
an existing `Privilege` row with a clean 400 (`unknown_privilege`), not
a silently-ignored value or an auto-created row. Matches the old
backend's frontend being a fixed multi-select rather than a free-text
field — the API now enforces what the UI only assumed.

## Security properties (each has a test)

| Property | Why | Test |
|---|---|---|
| Every LOB/Team/Group/Role write requires `security:manage` | Reads are open (matches the old backend's unrestricted dropdowns); writes are not | `test_creating_a_*_requires_security_manage_privilege` in each test file |
| Every write requires authentication | No anonymous security-management access | `test_creating_a_lob_requires_authentication` |
| Concurrent duplicate-name creation doesn't 500 | Same check-then-insert race as Phase 1/2, same fix (catch `IntegrityError`, convert to 409) | `test_concurrent_duplicate_lob_creation_never_500s` |
| Duplicate membership (same user, same scope, same admin/member-ness) is a clean 409 | The partial-unique-index fix above, exercised end-to-end | `test_adding_same_member_twice_is_a_clean_conflict_not_500` |
| Admin and plain-member rows stay genuinely separate | A user in one list must not silently appear in the other | `test_admin_and_member_lists_are_separate`, `test_admin_membership_is_distinguished_from_plain_membership` |
| A group can link to multiple LOBs and multiple Teams | The actual regression test for the Phase 1 schema bug this phase fixes | `test_group_can_link_to_multiple_lobs_and_multiple_teams` |
| Unlinking a shared LOB from one group doesn't affect another group that also has it | M2M tables are easy to get this wrong on with a naive "set the FK" mental model | `test_unlinking_a_lob_from_one_group_does_not_affect_another_group_sharing_it` |
| Unknown privilege name is a clean 400, not silently ignored or auto-created | Closed-catalog rule enforced at the API | `test_create_role_with_unknown_privilege_name_is_a_clean_400_not_a_silent_no_op` |
| `/groups/mine` returns only groups the caller actually belongs to | Backs the recon-creation dropdown directly — getting this wrong leaks group names to everyone | `test_groups_mine_returns_only_groups_the_caller_belongs_to` |
| Recon↔Group link/unlink round-trips correctly, and linking to a nonexistent group is a clean 404 | The actual gap this phase's investigation started from | `test_recon_can_be_linked_and_unlinked_to_a_group`, `test_linking_a_recon_to_a_nonexistent_group_is_404` |

45 tests carried over from Phase 1/2 plus 30 new tests here — 75 total,
all passing against a real `dart_test` Postgres database.

## Known gaps — explicit, not accidental (Phase 4+ / future work)

- **`group_roles` doesn't feed into `user_has_privilege`.** Linking a
  Role to a Group is fully functional as data (create it, link it,
  see it in `GroupDetails.role_names`), but a privilege granted that
  way does **not** currently flow through to `require_privilege()`
  checks for that group's members — that's real old-backend behavior
  (`f_validate_access` computed exactly this union), deliberately
  deferred rather than guessed at. `app/models/security.py`'s
  `Membership` docstring flags the exact extension point.
- **No tiered/scoped delegation.** `security:manage` is all-or-nothing;
  a "LOB admin" role in the old backend's four-tier sense isn't wired
  to any actual authorization narrower than that global privilege.
- **`req_level`/role-tier has no equivalent in `/users/me`.** The
  reference frontend's Recon Security page uses a coarser
  account/lob/team/group tier (separate from fine-grained privileges)
  to decide tab visibility; the current frontend integration hardcodes
  `role: []`. Not addressed this phase — flagged for whichever phase
  takes on the full Recon Security page rewrite (see below).
- **User invitation/registration (`manage_users`: invite, reg/nonreg
  lists, token validation) is a distinct surface, not built.** Phase 1
  built direct admin-creates-user-with-password (`POST /users`), which
  is simpler and more secure than the old backend's invite flow (which
  emails a plaintext generated password — a real anti-pattern, not
  replicated here on purpose). If invite-based provisioning is wanted
  later, design it as a proper token-based "set your own password"
  flow, not a port of the old email-plaintext-password behavior.
- **The full "Manage Recon Security" frontend page (30 files under
  `src/features/recon-security/`) is NOT rewired to the new backend.**
  Only the specific confirmed gap — the group dropdown in the
  recon-creation dialog — was fixed and verified live. The rest of that
  page still calls the old backend. Wiring the whole page is comparable
  in size to Phase 2's frontend integration and deserves its own pass,
  not a rushed bundling into this phase.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # applies Phase 1, 2, and 3 migrations
uv run python -m app.db.seed             # idempotent — seeds security:manage, the Admin role, and the 10-item recon privilege catalog
uv run uvicorn app.main:app --reload
uv run pytest                             # 75 tests total (30 Phase 1 + 15 Phase 2 + 30 Phase 3), real dart_test Postgres, no mocks
```

## Postman collection

`postman/DART_Backend_Phase3.postman_collection.json`, same environment
file as Phase 1/2. Self-contained (provisions its own users via the
bootstrap admin). Verified via Newman against a live server: 27/27
requests, 35/35 assertions passing.

```bash
npx newman run Backend/postman/DART_Backend_Phase3.postman_collection.json \
  --environment Backend/postman/DART_Backend_Local.postman_environment.json
```

## Frontend integration (the specific fix, not the full page)

- `src/features/recon-pipeline/api/list-my-groups.ts` (new) — calls
  `GET /api/v1/groups/mine`.
- `src/features/recon-pipeline/components/create-recon-dialog.tsx` —
  the Group field is back, required, and only ever offers groups the
  caller already belongs to. If the caller belongs to no group, the
  dropdown says so and the dialog can't be submitted — matching the old
  backend's actual constraint (recon creation requires a group) rather
  than silently allowing an orphaned recon.
- `src/features/recon-pipeline/api/create-recon.ts` — `createRecon` now
  does the old backend's real two-step flow: `POST /api/v1/recons`,
  then `POST /api/v1/recons/{id}/groups/{groupId}`. Not atomic — if the
  link step fails after create succeeds, the recon exists ungrouped
  rather than the whole operation rolling back, same shape as the old
  backend (two separate calls, no transaction spanning both).
- Verified live in the actual browser (not just curl): logged in as
  the bootstrap admin, opened Create Recon, confirmed the dropdown
  showed exactly the one group the admin belongs to, created a recon
  with it selected, and confirmed via a direct API check that the
  created recon's `group_name` was set correctly.

## Extending this (Phase 4+)

**Wiring `group_roles` into live authorization:** extend
`user_has_privilege` (`app/core/permissions.py`) to also check: is the
target privilege granted by any Role linked (via `group_roles`) to any
Group the user has a `Membership` row in (any role_id, including
NULL)? Add the test for "a role attached to a group I'm in grants me
that role's privileges" before wiring this in, so the very real risk of
a privilege-escalation bug in this join gets caught before it ships.

**Rewiring the full Manage Recon Security page:** follow this phase's
LOB/Team/Group/Role endpoints exactly — every field the frontend's
`api/*.ts` files under `src/features/recon-security/` currently expect
maps directly to a route already built here, just id-based instead of
the old backend's name-based calls (same id-not-name shift Phase 2 made
for Recon). The one piece not yet backed by an endpoint is the
account/lob/team/group tier read by `useVisibleTabs()` — decide how
that's computed (superuser → account tier; widest `Membership.scope_
type` a user holds → lob/team/group tier is one reasonable mapping)
before starting that rewrite.
