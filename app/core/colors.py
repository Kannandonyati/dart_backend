"""ANSI color codes for local console log output.

Only ever used when LOG_JSON=false (local/dev console rendering) — never
wrap a JSON log line in escape codes, that corrupts the machine-readable
output every aggregator/parser downstream expects in staging/production.
`colorize()` enforces that itself rather than trusting call sites to
remember.
"""

import sys

from app.core.config import settings

RED = "\033[31m"  # error
GREEN = "\033[32m"  # success
YELLOW = "\033[33m"  # warning
BLUE = "\033[34m"  # info
MAGENTA = "\033[35m"  # alert / critical
CYAN = "\033[36m"  # notice / debug
RESET = "\033[0m"

_enabled = (not settings.log_json) and sys.stdout.isatty()


def colorize(text: str, code: str) -> str:
    if not _enabled:
        return text
    return f"{code}{text}{RESET}"
