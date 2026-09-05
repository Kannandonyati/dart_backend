"""Per-request path, so audit rows can store the old User Logs Request URL."""

from contextvars import ContextVar

_request_path: ContextVar[str | None] = ContextVar("dart_request_path", default=None)


def set_request_path(path: str | None) -> None:
    _request_path.set(path)


def get_request_path() -> str | None:
    return _request_path.get()
