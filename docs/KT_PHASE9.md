# KT — Phase 9: Audit Logs & Maintenance

Knowledge transfer for what was actually built, why it's shaped the way
it is, and how to run/test/extend it. This is the last of the 9
planned phases — companion docs: `KT_PHASE1.md` through `KT_PHASE8.md`,
`../architecture.md`, `BUILD_PLAN.md`.

## The core correction this phase made to its own starting assumption

"Audit Logs & Maintenance" reads as one phase name but maps to two
separate old-backend apps, confirmed by reading both directly before
writing any code:

- **Audit Logs** = `Logentries` (`user_logs`/`all_logs`/`export`) — a
  single system-wide log table populated somewhere inside the same
  opaque `sp_master` stored-procedure layer every prior phase has found
  gaps in. Not readable Python; same resolution as always (define a
  clean contract, document the decision — see `app/models/audit.py`'s
  docstring).
- **Maintenance** = `manage_users` (`user/invite`, `forgot/password`,
  `reset/password`, `invite/list`, `delete/user`) — a real, currently-
  missing gap in *this* backend, not a stored-procedure black box.
  Phase 1 built login/register/list but never invite, password reset,
  or deactivation. This phase fills that gap.

**A real access-control bug in the old backend, found and deliberately
not replicated.** `Logentries/views.py`'s `all_logs` and `export`
endpoints are decorated only with `@permission_classes((IsAuthenticated,))`
— no privilege check beyond being logged in. Read literally, that means
any authenticated user could view every recon's system-wide audit
trail, including recons they have no access to. This project has
already documented one denial-side bug in the old backend's access
model (`f_validate_access`, see `app/core/permissions.py`'s docstring);
this is the disclosure-side counterpart, closed the same way: `GET
/audit-logs` and `/audit-logs/export` require `is_superuser`.

## What's here

| Table | File | Purpose |
|---|---|---|
| `audit_logs` | `app/models/audit.py` | Insert-only `(actor, recon, action, entity, detail, created_at)` trail |

| Module | File | Purpose |
|---|---|---|
| Recording helper | `app/core/audit.py` | `record_audit_log()` — stages an insert, rides the caller's existing commit |
| Audit reads | `app/api/v1/endpoints/audit_logs.py` | Global (superuser), mine, per-recon, CSV export |
| User maintenance | `app/api/v1/endpoints/user_maintenance.py` | Invite, accept-invite, admin-mediated password reset, list-invited, deactivate |
| Token types | `app/core/security.py` | `TokenType.INVITE` / `TokenType.PASSWORD_RESET` added to the existing JWT machinery |

## Why it's shaped this way

**Audit logging is wired into a deliberately small, high-value subset
of endpoints — not every mutation across all 8 prior phases.**
`record_audit_log()` is called from exactly four places: `recons.py`'s
create/update/delete (the clearest "who changed what" events in the
whole system) and `report_data.py`'s `signoff` (which Phase 8's own KT
already flagged as "exactly the kind of event an audit trail should
capture"). Retrofitting audit calls into every mutating endpoint across
Phases 3-8 was considered and rejected: it would touch dozens of
already-shipped, already-tested call sites for marginal benefit over
recording the handful of decisions that actually matter (recon
lifecycle, sign-off), and it's a mechanical, low-risk addition to make
incrementally later — add one `record_audit_log()` call per endpoint
that needs one, following the exact pattern already in `recons.py` and
`report_data.py`, not a redesign.

**`record_audit_log()` never calls `db.commit()` itself.** It stages
the `AuditLog` insert on the caller's existing session and rides
whatever commit the endpoint was already about to do — recording an
audit entry costs zero extra round trips, and an audit row can never
be persisted for a mutation that itself rolled back. This is why
`recons.py`'s create/update endpoints changed their internal write from
`db.commit()` to `db.flush()` followed by `record_audit_log()` then
`db.commit()` — the flush surfaces any `IntegrityError` (the existing
"name already taken" race) before the audit row is even staged,
preserving the exact same error behavior as before this phase touched
that file.

**A recon-scoped audit trail deliberately survives the recon's own
deletion.** `GET /recons/{id}/audit-logs` does NOT use the shared
`get_accessible_recon` helper every other pipeline-stage endpoint
uses — that helper filters out soft-deleted recons (`deleted_at IS NOT
NULL`), which would make a recon's own `recon.deleted` event, and
everything that happened before it, permanently unreviewable the
moment the recon is deleted. This was caught live: an early version of
this endpoint used `get_accessible_recon` and a test asserting "the
audit trail is readable after delete" failed with 404. The endpoint now
loads the recon regardless of deletion state and applies the same
ownership check (`can_manage_recon`) directly — see the endpoint's own
comment.

**Password reset and invite are admin-mediated, not self-service
email — a security-motivated deviation from what the old backend
presumably did, not a straight port.** This codebase has no SMTP/email
integration (confirmed: nothing in `app/core/config.py` configures
one). A true self-service "forgot password" endpoint would have to
either not exist, or hand a password-reset token back to an
*unauthenticated* caller who merely claims an email address — a live
account-takeover primitive, not a documented limitation. Instead: an
admin (`user:manage`) generates an invite or reset token through a
privileged endpoint and delivers it to the user out-of-band; the user
redeems it through a public endpoint — the same bearer-token-redemption
model a real self-service flow uses for the redemption half. The only
gap versus production self-service is *delivery* (manual vs. emailed),
a small independent follow-up once an email integration exists.

**Invite/reset tokens are short-lived signed JWTs, reusing the existing
`TokenType` machinery (`app/core/security.py`), not a new database
table.** Two new type values (`INVITE`, `PASSWORD_RESET`) plus two new
`Settings` fields for their expiry (`invite_token_expire_days=7`,
`password_reset_token_expire_hours=24`) were the only additions needed
— `_create_token`/`decode_token` already handle signing, expiry, and
type-checking. Same trade-off already accepted for access/refresh
tokens (see that module's own docstring): no revocation store exists,
so a leaked token is valid until it naturally expires. Not a new gap
introduced by this phase — the existing one, extended to two more token
types.

**An invited user's placeholder password is a real Argon2 hash of an
unguessable random value, not a sentinel string — found and fixed
live.** The first version used a plain string like `"!invited:" +
uuid4().hex` as `hashed_password`, reasoning it would simply never
match any real login attempt. It broke `test_invite_accept_and_login_flow`
instead: passlib's `verify()` raises `UnknownHashError` (surfacing as an
unhandled 500) on a string it can't identify as *any* known hash
scheme — it doesn't fail closed the way a wrong-but-well-formed hash
comparison would. Fixed to `hash_password(uuid.uuid4().hex)`: a
syntactically valid Argon2 hash of a value nobody will ever supply, so
`verify_password` runs its normal comparison and correctly returns
`False` until the invite is redeemed and a real password is set.

**Deactivation is soft (`is_active=False`), not a hard delete** — same
precedent as Recon's soft delete (Phase 2). The old backend's
`delete_user` semantics aren't visible in readable Python (opaque
stored-proc call), so this follows the established pattern rather than
guessing at hard-delete semantics that would need to cascade through
every FK a user is referenced from (owned recons, created imports,
audit rows' `actor_user_id`, which uses `ondelete="SET NULL"`
specifically so a deactivated-not-deleted user's history stays
attributable).

## Security properties (each has a test)

| Property | Why | Test |
|---|---|---|
| Global audit log requires `is_superuser` | Closes the old backend's apparent any-authenticated-user disclosure gap | `test_global_audit_log_requires_superuser` |
| A user's "mine" view only shows their own actions | No cross-user disclosure via the personal-activity view | `test_mine_audit_log_scoped_to_caller` |
| A recon-scoped audit trail is still readable after the recon is deleted | The one thing an audit trail must survive is the deletion it's recording | `test_recon_lifecycle_is_audited` |
| Recon create/update/delete and report sign-off are recorded | The four wired-in, high-value events actually produce rows | `test_recon_lifecycle_is_audited`, `test_report_signoff_is_audited` |
| Invite/reset-token generation/deactivation require `user:manage` | No unprivileged account takeover via these endpoints | `test_invite_requires_privilege` |
| An invited user cannot log in before accepting, can immediately after | The whole point of the two-stage flow | `test_invite_accept_and_login_flow` |
| A garbage/invalid invite or reset token is rejected, not silently accepted | `decode_token`'s signature/expiry/type checks are actually enforced here | `test_invalid_invite_token_is_rejected` |
| A password reset invalidates the old password immediately | Old credential can't coexist with the new one | `test_admin_mediated_password_reset_flow` |
| A deactivated user cannot log in | `is_active` is actually checked at login, not just stored | `test_deactivate_user_blocks_login` |
| Duplicate invite (existing email/username) is rejected | Same collision handling as `POST /users` | `test_duplicate_invite_is_conflict` |

154 tests total (30 Phase 1 + 15 Phase 2 + 30 Phase 3 + 18 Phase 4 + 15
Phase 5 + 13 Phase 6 + 9 Phase 7 + 12 Phase 8 + 12 Phase 9), all passing
against a real `dart_test` Postgres database, mypy-clean, ruff-clean.
This is the first phase with no Celery/async-task involvement at all —
every endpoint here is synchronous, so there's nothing new to say about
the event-loop or bulk-update patterns documented in Phase 5/6.

## Known gaps — explicit, not accidental

- **No revocation store for invite/reset (or access/refresh) tokens.**
  Inherited from Phase 1's original design, now extended to two more
  token types rather than newly introduced. A leaked token is valid
  until it expires. If this needs closing later, it's a Redis-backed
  jti blocklist checked in `decode_token`'s callers — a bounded,
  well-understood addition, not a redesign.
- **No email delivery.** Invite/reset tokens are handed back to the
  *admin* caller, who must deliver them to the actual user out-of-band.
  Wiring in a real email provider is independent, additive work once
  one is chosen — nothing here needs to change shape to support it,
  the token-issuing endpoints just gain a side effect.
- **Audit logging is not wired into Phases 3-7's endpoints** (dimension
  config, imports, bridge mappings, sync mappings, group/team/role
  management). Deliberately scoped to the four highest-value call
  sites for this phase (see "Why it's shaped this way" above) rather
  than a sweeping, higher-risk change across every already-shipped
  endpoint. Extending coverage is mechanical: import `record_audit_log`
  and call it once per additional endpoint that needs one.
- **No archive/retention policy for `audit_logs`.** It's an insert-only,
  unbounded table, same shape as `ImportedRow` (Phase 5) — not yet
  partitioned by time or recon, documented there as a follow-up once
  real data volume justifies it, and the same follow-up applies here.
- **The reference frontend has no Audit Log or user-invite/reset UI
  wired to this backend** — same scoping precedent as every prior
  phase: backend, tests, and Postman collection complete; frontend is a
  separate, appropriately-sized follow-up.

## Running it

```bash
cd Backend
uv run alembic upgrade head              # applies Phase 1-9 migrations (final set)
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload     # API
uv run pytest                             # 154 tests total, real dart_test Postgres, no mocks
```

No Celery worker or Redis is needed for anything in this phase.

## Postman collection

`postman/DART_Backend_Phase9.postman_collection.json`, same environment
file as Phase 1-8. No fixtures needed — every request in this
collection is JSON, no file uploads. Verified via Newman against a live
server: 42/42 requests, 23/23 assertions passing.

**A real Postman-collection pacing bug found and fixed live, same class
as Phase 1's documented 5/minute login rate limiter tripping under
rapid Newman runs.** This collection makes 7 calls to `/auth/login`
(bootstrap admin, User B, invite-then-fail, invite-then-succeed,
old-password-fails, new-password-works, deactivated-fails) — enough to
exceed the limiter's 5/minute budget if they land inside the same
window. Fixed with the same shape of fix Phase 5/6 used for async job
polling, applied here to a rate limiter instead: a "Wait for
`/auth/login` rate-limit window to reset" step (a cheap `GET /health`
polled every 3s via `postman.setNextRequest`) inserted before the run
of login calls that would otherwise land in the same 60-second window
as the Setup folder's earlier logins.

```bash
cd Backend/postman
npx newman run DART_Backend_Phase9.postman_collection.json \
  --environment DART_Backend_Local.postman_environment.json
```

## All 9 phases: final state

| Phase | Subject | Tests |
|---|---|---|
| 1 | Auth, users, JWT | 30 |
| 2 | Recon core | 15 |
| 3 | Groups, teams, roles, LOBs | 30 |
| 4 | Recon apps, dimensions | 18 |
| 5 | Run Import | 15 |
| 6 | Bridge Members | 13 |
| 7 | Transformation (Sync Mapping) | 9 |
| 8 | Run Report | 12 |
| 9 | Audit Logs & Maintenance | 12 |
| **Total** | | **154** |

Every phase: real Postgres-backed tests (no mocks), mypy-clean,
ruff-clean, a Postman collection verified live via Newman against a
running server (and, where relevant, a live Celery worker), and a KT
doc documenting the real design decisions and bugs found along the way.
Known gaps are listed explicitly in each phase's KT rather than
silently dropped — see each `KT_PHASE*.md`'s own "Known gaps" section
for what's deliberately out of scope and why.
