"""Next-run calculation for 5-field cron expressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.exceptions import AppError

_MAX_SCAN = timedelta(days=366)


def parse_cron_field(expr: str, minimum: int, maximum: int) -> frozenset[int]:
    values: set[int] = set()
    for part in expr.split(","):
        step = 1
        body = part
        if "/" in part:
            body, step_s = part.split("/", 1)
            step = int(step_s)
            if step < 1:
                raise ValueError("cron step must be >= 1")
        if body in {"*", ""}:
            start, end = minimum, maximum
        elif "-" in body:
            start_s, end_s = body.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(body)
        values.update(range(start, end + 1, step))
    out = frozenset(v for v in values if minimum <= v <= maximum)
    if not out:
        raise ValueError("cron field matches nothing")
    return out


def _weekday(moment: datetime) -> int:
    """Cron weekday: 0 and 7 are Sunday."""
    return (moment.weekday() + 1) % 7


_ONCE_PREFIX = "@once "


def _once_utc(stamp: str, timezone: str, after: datetime) -> datetime | None:
    try:
        tz = ZoneInfo(timezone)
        when = datetime.fromisoformat(stamp.strip())
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise AppError("schedule_cron or timezone is invalid.", code="invalid_cron") from exc
    if when.tzinfo is None:
        when = when.replace(tzinfo=tz)
    local_after = after.astimezone(tz)
    start_of_today = local_after.replace(hour=0, minute=0, second=0, microsecond=0)
    if when < start_of_today:
        return None
    utc = when.astimezone(UTC)
    if utc <= after:
        return after
    return utc


def next_scheduled_at(expr: str | None, timezone: str, after: datetime) -> datetime | None:
    if not expr:
        return None
    if expr.startswith(_ONCE_PREFIX):
        return _once_utc(expr.removeprefix(_ONCE_PREFIX), timezone, after)
    return next_cron_utc(expr, timezone, after)


def is_once_schedule(expr: str | None) -> bool:
    return expr is not None and expr.startswith(_ONCE_PREFIX)


def next_cron_utc(expr: str, timezone: str, after: datetime) -> datetime:
    fields = expr.split()
    if len(fields) != 5:
        raise AppError("schedule_cron must have 5 fields (m h dom mon dow).", code="invalid_cron")
    try:
        tz = ZoneInfo(timezone)
        minute_s, hour_s, day_s, month_s, dow_s = fields
        minutes = parse_cron_field(minute_s, 0, 59)
        hours = parse_cron_field(hour_s, 0, 23)
        days = parse_cron_field(day_s, 1, 31)
        months = parse_cron_field(month_s, 1, 12)
        dows = parse_cron_field(dow_s, 0, 7)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise AppError("schedule_cron or timezone is invalid.", code="invalid_cron") from exc

    if 7 in dows:
        dows = frozenset(dows | {0}) - {7}

    cursor = after.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    deadline = cursor + _MAX_SCAN
    while cursor <= deadline:
        if (
            cursor.month in months
            and cursor.day in days
            and cursor.hour in hours
            and cursor.minute in minutes
            and _weekday(cursor) in dows
        ):
            return cursor.astimezone(UTC)
        cursor += timedelta(minutes=1)
    raise AppError("schedule_cron never matches in the next year.", code="invalid_cron")
