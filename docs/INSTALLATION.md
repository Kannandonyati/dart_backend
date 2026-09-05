# Installation & Dependencies

Native, no-Docker setup for the DART backend: Python tooling, PostgreSQL,
and Redis, on Windows, Linux, or WSL. If you'd rather skip all of this,
`docker compose up --build` from `Backend/` gets you the whole stack —
Postgres, Redis, and the API — without installing anything below. This
doc is for when you want everything running natively instead.

## 1. Python tooling: uv

This project uses [`uv`](https://docs.astral.sh/uv/) only — no `venv`, no
`pip`, no Poetry. `uv` manages the Python version, the virtual
environment, and the dependency lockfile in one tool.

**Windows (PowerShell):**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Verify: `uv --version`. Then, from `Backend/`:
```bash
uv sync --dev
```
This creates `.venv` and installs everything from `pyproject.toml` /
`uv.lock`. See the main `README.md` for day-to-day commands
(`uv run uvicorn ...`, `uv run pytest`, etc.).

## 2. PostgreSQL

The app needs a reachable Postgres server and a `dart` role/database
(the names/credentials `.env.example` documents — change them if you
want, just keep `.env` consistent).

### 2a. If you don't have Postgres yet

- **Windows:** install from [postgresql.org](https://www.postgresql.org/download/windows/)
  (the EnterpriseDB installer registers it as a Windows service, so it
  starts automatically — this is simpler than a bundled/portable
  install that has no service and must be started manually every time,
  see the note below).
- **Linux (Debian/Ubuntu):**
  ```bash
  sudo apt update
  sudo apt install postgresql postgresql-contrib
  sudo systemctl enable --now postgresql
  ```
- **Linux (Fedora/RHEL):**
  ```bash
  sudo dnf install postgresql-server postgresql-contrib
  sudo postgresql-setup --initdb
  sudo systemctl enable --now postgresql
  ```

### 2b. If you already have Postgres running

You just need the role and database this app expects. Connect as a
superuser (commonly `postgres`) and run:

```sql
CREATE ROLE dart WITH LOGIN PASSWORD 'your-password-here';
CREATE DATABASE dart OWNER dart;
```

Non-interactively:
```bash
psql -U postgres -h localhost -p 5432 -c "CREATE ROLE dart WITH LOGIN PASSWORD 'your-password-here';"
psql -U postgres -h localhost -p 5432 -c "CREATE DATABASE dart OWNER dart;"
```

Run these as **two separate `psql -c` invocations**, not one command
with both statements joined by `;` — `psql -c` wraps a multi-statement
string in a single implicit transaction, and `CREATE DATABASE` cannot
run inside a transaction block. Combining them fails, and rolls back the
`CREATE ROLE` too.

### 2c. Point `.env` at it

```
DATABASE_URL=postgresql+asyncpg://dart:your-password-here@localhost:5432/dart
```

**If the password contains special characters** (`@`, `:`, `/`, `#`,
etc.), URL-encode them — a raw `@` in the password is indistinguishable
from the `@` that separates credentials from the host, and the URL
parses wrong. Percent-encode at minimum: `@` → `%40`, `:` → `%3A`,
`/` → `%2F`, `#` → `%23`. Example: password `D@art_Dony@ti` becomes
`D%40art_Dony%40ti` in the URL.

### 2d. A note on bundled/portable Postgres installs

Some dev setups (e.g. a Postgres bundled alongside another tool rather
than installed via the official installer) don't register a Windows
service — nothing starts it automatically on boot or login. If
`database_check_failed` says `Connection refused` (not an auth error),
the server likely isn't running at all. Start it manually:

```powershell
# adjust the path to wherever that Postgres install actually lives
& "<postgres-install-dir>\bin\pg_ctl.exe" -D "<postgres-install-dir>\data" -l "<postgres-install-dir>\data\start.log" start
```

You'll need to do this every time you restart your machine, unless you
register it as a proper Windows service (`pg_ctl register`) or switch to
an installer-managed Postgres instead.

## 3. Redis

Redis backs the cache and the Celery queue broker (see
`../../architecture.md` §3–4 for why). Both point at the same server —
`REDIS_URL` and `CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` in `.env`
just use different logical DB numbers on it, so one running server
satisfies all three.

### Windows

Windows has no official Redis build. Use **[Memurai](https://www.memurai.com/)**
— a Redis-compatible server built natively for Windows, installs as a
Windows service, and starts automatically listening on `localhost:6379`
(no manual "start the server" step, unlike the bundled-Postgres case
above).

```powershell
winget install --id Memurai.MemuraiDeveloper --accept-source-agreements --accept-package-agreements
```

A Windows admin/UAC prompt will appear — approve it (this can only be
approved interactively; it cannot be scripted or approved from a
non-interactive session). If `winget` isn't available or you'd rather
not use it, download the installer directly from
[memurai.com](https://www.memurai.com/get-memurai).

**Verify:**
```powershell
Get-Service -Name Memurai
Test-NetConnection -ComputerName localhost -Port 6379
```

### Linux (native)

**Debian/Ubuntu:**
```bash
sudo apt update
sudo apt install redis-server
sudo systemctl enable --now redis-server
```

**Fedora/RHEL:**
```bash
sudo dnf install redis
sudo systemctl enable --now redis
```

**Verify:**
```bash
redis-cli ping   # should print PONG
```

### WSL (Windows Subsystem for Linux)

If you're running the app natively on Windows but want Redis inside
WSL2 rather than installing Memurai, this works too — WSL2 forwards
`localhost` between Windows and the WSL distro automatically, so
`REDIS_URL=redis://localhost:6379/...` from the Windows-side app reaches
Redis running inside WSL without any extra networking setup.

```bash
wsl                       # enter your WSL distro
sudo apt update
sudo apt install redis-server
sudo service redis-server start   # or: sudo systemctl enable --now redis-server, if your WSL distro has systemd enabled
redis-cli ping             # should print PONG, confirms it's up
```

Unlike a real systemd-managed Linux install, a default WSL distro
without systemd won't auto-start Redis on its own boot — you'll need to
`wsl` in and run `sudo service redis-server start` again after each
Windows restart, unless you've enabled `systemd` in WSL's
`/etc/wsl.conf` (`[boot]\nsystemd=true`) or set up WSL to auto-launch it.

### Point `.env` at it (same for all three platforms)

```
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
```

## 4. Verify everything together

```bash
uv run uvicorn app.main:app --reload
```

Look for these lines (see `app/core/startup.py`):

```
startup_checks_started      environment=local strict=False
database_connected          detail=postgresql+asyncpg://***:***@localhost:5432/dart
redis_cache_connected       detail=redis://localhost:6379/0
queue_broker_connected      detail=redis://localhost:6379/1
startup_checks_passed
```

If any of the three show `..._check_failed` instead, startup raises
`StartupCheckFailed` and the process exits — Postgres, Redis cache, and
the queue broker are all required. A `Connection refused` / timeout
error means the server isn't running; an auth/role error means the
server is up but the credentials/role in `.env` don't match what you
created above.
