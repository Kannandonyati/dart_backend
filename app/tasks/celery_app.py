"""Celery application — the queue layer (architecture.md §4: Celery + Redis).

Chosen over Redis Streams (would mean hand-rolling retries/routing/dead-
lettering) and over RabbitMQ+Celery+Redis (a second broker technology to
operate, only worth it past Redis's delivery-guarantee ceiling — revisit
if that's actually hit) and over AWS SQS (adds cloud lock-in with no
matching benefit until the whole platform is committed to AWS). Reuses the
same Redis instance already required for caching (separate logical DBs:
broker on db 1, result backend on db 2 — see Settings).

This is intentionally the *queue infrastructure only*. Real tasks (file
import, bridge computation, transformation runs, report generation) get
added as the reconciliation API is built — `app.tasks.import_tasks`
(Phase 5: Run Import) was the first; `app.tasks.bridge_tasks` (Phase 6:
Bridge Members) is the second. The `health_check_task` that used to
prove the worker/broker/backend wiring before any real task existed has
been removed per its own docstring's instruction.
"""

from celery import Celery
from celery.signals import setup_logging

from app.cache.redis import resolve_loopback_url
from app.core.config import settings

celery_app = Celery(
    "dart",
    broker=resolve_loopback_url(str(settings.celery_broker_url)),
    backend=resolve_loopback_url(str(settings.celery_result_backend)),
    include=["app.tasks.import_tasks", "app.tasks.bridge_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],  # never accept pickle — arbitrary deserialization is RCE
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,  # a worker crash mid-task re-queues it instead of losing it
    worker_prefetch_multiplier=1,  # fair dispatch for long-running file-processing tasks
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    # A `.delay()` call from a request handler must not hang the request
    # if the broker is briefly unreachable — cap retries so it raises
    # quickly (the caller gets a real error to retry) instead of Celery's
    # old default of retrying forever. Found by an actual hang: the first
    # Run Import test run against a broker with nothing listening blocked
    # past a 120s timeout before this was set.
    broker_connection_timeout=2,
    broker_connection_max_retries=1,
)


@setup_logging.connect  # type: ignore[untyped-decorator] # celery ships no stubs/py.typed marker
def _configure_celery_logging(**_kwargs: object) -> None:
    """Route Celery's logging through the same structlog config as the API,
    instead of Celery's own default formatter, so worker logs and API logs
    are one consistent shape in whatever aggregator reads them."""
    from app.core.logging import configure_logging

    configure_logging()
