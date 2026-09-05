# Startup failures: Postgres and Redis

How `uv run uvicorn app.main:app --reload` failed on this Windows machine, and what was done to get it running.

## 1. Postgres: connection refused on port 5432

### Symptom

```
database_check_failed  detail=postgresql+asyncpg://***:***@localhost:5432/dart
error=[Errno 10061] Connect call failed ('127.0.0.1', 5432)
StartupCheckFailed: Dependencies unreachable: database
Application startup failed. Exiting.
```

### Cause

The API always requires Postgres (`app/core/startup.py`). Nothing was listening on `127.0.0.1:5432`.

This machine uses the **bundled** Postgres under `C:\Users\KannanSubramaniyan\Dart\DART_Tools\postgres`. It is **not** a Windows service, so it does not start after a reboot. Docker Desktop was also stopped, so Compose was not an option.

The `dart` role and `dart` database already existed; the server process was simply down.

### Fix

Start the bundled cluster:

```powershell
& "C:\Users\KannanSubramaniyan\Dart\DART_Tools\postgres\bin\pg_ctl.exe" `
  -D "C:\Users\KannanSubramaniyan\Dart\DART_Tools\postgres\data" `
  -l "C:\Users\KannanSubramaniyan\Dart\DART_Tools\postgres\data\start.log" `
  start
```

After this, port 5432 accepted connections and the app logged `database_connected`.

Repeat this after every reboot (or register Postgres as a Windows service / use Docker).

---

## 2. Redis / queue: timeout on port 6379

### Symptom (first run)

With `ENVIRONMENT=local`, Redis cache and the Celery broker were **warnings only**. The API still started:

```
redis_cache_check_failed   error=Timeout connecting to server
queue_broker_check_failed  error=Timeout connecting to server
startup_checks_incomplete  failed=['redis_cache', 'queue_broker']
```

### Code change (requested)

Redis cache and the queue broker were made **mandatory**, same as Postgres, in `app/core/startup.py`. A test covers this in `tests/test_startup.py`. Docs in `docs/INSTALLATION.md` were updated.

After that change, missing Redis **exits** startup:

```
redis_cache_check_failed   error=Timeout connecting to server
queue_broker_check_failed  error=Timeout connecting to server
startup_checks_failed      failed=['redis_cache', 'queue_broker']
StartupCheckFailed: Dependencies unreachable: redis_cache, queue_broker
```

### Cause

`.env` points at `redis://127.0.0.1:6379`. Windows port **6379 was closed**.

Ubuntu WSL had `redis-server` running, but it was bound only to **WSL’s own** `127.0.0.1`. That is not the same as Windows `127.0.0.1`, so the FastAPI process never saw Redis.

### Fix

Docker Desktop was started, then a Redis container was published on the Windows host:

```powershell
docker run -d --name dart-redis --restart unless-stopped -p 6379:6379 redis:7-alpine
```

Startup then reported:

```
database_connected
redis_cache_connected
queue_broker_connected
startup_checks_passed
```

Keep **Docker Desktop** running. `--restart unless-stopped` brings the container back when Docker starts; if Desktop is stopped, Redis on 6379 disappears again.

---

## Run the API

Postgres must be up (step 1). Docker Redis must be up (step 2). Then:

```powershell
cd C:\Users\KannanSubramaniyan\API_Modal\dart_backend
uv run uvicorn app.main:app --reload
```

Expect `dart_backend_ready` and `http://127.0.0.1:8000`.
