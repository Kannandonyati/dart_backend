"""5-field cron next-run helper used by the workflow scheduler."""

from datetime import UTC, datetime

import pytest

from app.core.exceptions import AppError
from app.services.workflow_schedule import next_cron_utc, next_scheduled_at, parse_cron_field


def test_parse_star_and_step() -> None:
    assert parse_cron_field("*", 0, 5) == frozenset({0, 1, 2, 3, 4, 5})
    assert parse_cron_field("*/15", 0, 59) == frozenset({0, 15, 30, 45})
    assert parse_cron_field("1,2,9", 0, 10) == frozenset({1, 2, 9})


def test_hourly_cron_advances_to_next_hour() -> None:
    after = datetime(2026, 9, 17, 10, 5, tzinfo=UTC)
    nxt = next_cron_utc("0 * * * *", "UTC", after)
    assert nxt == datetime(2026, 9, 17, 11, 0, tzinfo=UTC)


def test_invalid_cron_is_app_error() -> None:
    after = datetime(2026, 9, 17, 10, 0, tzinfo=UTC)
    with pytest.raises(AppError) as exc:
        next_cron_utc("not-cron", "UTC", after)
    assert exc.value.code == "invalid_cron"


def test_once_keeps_a_future_datetime() -> None:
    after = datetime(2026, 9, 17, 15, 50, tzinfo=UTC)
    nxt = next_scheduled_at("@once 2026-09-17T21:22:00", "UTC", after)
    assert nxt == datetime(2026, 9, 17, 21, 22, tzinfo=UTC)


def test_once_today_in_the_past_is_due_immediately() -> None:
    after = datetime(2026, 9, 17, 21, 30, tzinfo=UTC)
    nxt = next_scheduled_at("@once 2026-09-17T21:22:00", "UTC", after)
    assert nxt == after


def test_tue_to_fri_window_at_clock_time() -> None:
    thursday = datetime(2026, 9, 17, 20, 0, tzinfo=UTC)
    assert next_cron_utc("54 21 * * 2-5", "UTC", thursday) == datetime(
        2026, 9, 17, 21, 54, tzinfo=UTC
    )
    friday_night = datetime(2026, 9, 18, 22, 0, tzinfo=UTC)
    assert next_cron_utc("54 21 * * 2-5", "UTC", friday_night) == datetime(
        2026, 9, 22, 21, 54, tzinfo=UTC
    )


def test_monthly_day_of_month() -> None:
    after = datetime(2026, 9, 10, 0, 0, tzinfo=UTC)
    assert next_cron_utc("0 9 15 * *", "UTC", after) == datetime(2026, 9, 15, 9, 0, tzinfo=UTC)


def test_yearly_month_and_day() -> None:
    after = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
    assert next_cron_utc("0 9 1 3 *", "UTC", after) == datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

