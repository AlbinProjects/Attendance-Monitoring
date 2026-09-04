"""
Shared office-timezone time helpers.

This is the ONLY place "now" and "today" are computed for business logic
across the app (attendance status, performance availability). Never use a
client-supplied timestamp or the server's raw UTC clock for anything
business-relevant — always go through here so every feature agrees on what
day and time it currently is, in the company's configured timezone.
"""

from datetime import date, datetime, time

import pytz

from app.config import Settings


def get_office_now(settings: Settings) -> datetime:
    """Current time, timezone-aware, in the configured office timezone."""
    tz = pytz.timezone(settings.office_timezone)
    return datetime.now(tz)


def get_office_today(settings: Settings) -> date:
    return get_office_now(settings).date()


def localize_time_on_date(settings: Settings, on_date: date, at_time: time) -> datetime:
    """
    Combine a calendar date with a time-of-day, producing a timezone-aware
    datetime in the office timezone. Used for both the "late" threshold
    (office_start_time + grace period) and the performance availability
    threshold (performance_start_time) — the two places the app needs to
    ask "has clock time X on date Y passed yet, in company time?".
    """
    tz = pytz.timezone(settings.office_timezone)
    return tz.localize(datetime.combine(on_date, at_time))
