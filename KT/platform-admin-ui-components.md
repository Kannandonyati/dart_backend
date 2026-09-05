# Platform admin and UI component visibility

A second admin tier sits above Account Admin / `is_superuser`. Only this
account can switch sidebar groups, pages, tabs, and pipeline stages on or
off for everyone else.

## Why a new flag

`is_superuser` is not exclusive: giving someone the "Account Admin" user
type sets it. If that were the gate for the console, any Account Admin
could hide Manage Users or Workflow Automation for the whole tenant,
including the people who appointed them.

`is_platform_admin` cannot be set through any API. The seed script is the
only writer (`PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD`).

## Credentials (local)

```
email:    dartsuper@admin.com
password: super@admin123
```

Create / promote the account with:

```powershell
cd C:\Users\KannanSubramaniyan\API_Modal\dart_backend
uv run alembic upgrade head
uv run python -m app.db.seed
```

Then sign in and open **Platform → UI Components**.

## What a switch actually does

1. The catalog of toggleable things is code (`app/core/ui_components.py`),
   not a table, so it cannot drift from the frontend.
2. The database holds only *overrides*. Empty table = everything on.
3. Disabling a parent hides its children (Workflow Automation hides all
   six nested pages).
4. A per-role override beats the "everyone" baseline. If a user has two
   types with conflicting rows, enabled wins.
5. The platform admin always sees everything, so they cannot lock
   themselves out.
6. Pages with APIs also close those APIs (`403 component_disabled`).
   `/users/me` and `/users/directory` stay up when Manage Users is off,
   otherwise nobody could stay signed in. Invite/password-reset
   redemption (`/users/accept-invite`, `/users/reset-password`) stays
   public for the same reason.

Locked (cannot be switched off): the admin console itself, and the
Select stage of the pipeline.
