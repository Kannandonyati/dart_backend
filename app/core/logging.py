"""Structured logging setup.

JSON logs in staging/production (machine-parseable, ships cleanly to any
log aggregator); readable console logs locally. Every log line carries a
`request_id` when it's emitted inside a request — see core.middleware —
so a single request's logs can be grepped out of a shared log stream,
which the stored-procedure `debug: true` NOTICE-tracing workflow this
project used to rely on never gave us.

No secrets in logs: never log a raw password, token, or full Authorization
header anywhere in this codebase — log the jti/subject if you need to
correlate a token to activity, never the token itself.
"""

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog

from app.core.colors import BLUE, CYAN, MAGENTA, RED, YELLOW
from app.core.config import settings

# Colorama translates ANSI escapes for legacy Windows consoles (cmd.exe);
# a no-op on anything that already understands them natively (Windows
# Terminal, PowerShell 7+, every Unix terminal) — safe to always call.
if not settings.log_json:
    import colorama

    colorama.just_fix_windows_console()

# Matches the palette used throughout local dev: red=error, yellow=warning,
# blue=info, magenta=critical/alert, cyan=debug/notice. Success (green) is
# applied explicitly at call sites for positive-outcome events (see
# app.core.startup) rather than tied to a log *level*, since "success" isn't
# a level Python logging has — see app.core.colors.colorize.
#
# Built on top of structlog's own defaults (get_default_level_styles()
# returns a plain dict at runtime, typed Any in structlog's own stubs)
# rather than a fresh dict, so "exception"/"notset"/"warn" keep sane
# defaults instead of falling back to an unstyled "" for any level this
# module doesn't explicitly override.
_LEVEL_STYLES: Any = structlog.dev.ConsoleRenderer.get_default_level_styles()
_LEVEL_STYLES.update(
    {
        "critical": MAGENTA,
        "error": RED,
        "warning": YELLOW,
        "warn": YELLOW,
        "info": BLUE,
        "debug": CYAN,
    }
)

_REDACTED = "***REDACTED***"
_SENSITIVE_KEYS = {"password", "token", "authorization", "secret", "access_token", "refresh_token"}


def _redact_sensitive(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
    )

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _redact_sensitive,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(level_styles=_LEVEL_STYLES)
    )

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(settings.log_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
