"""
Daily performance business logic.

The one rule everything here hinges on (see README "5 PM is the start
time"): PERFORMANCE_START_TIME is when today's report becomes available to
fill in, NOT a deadline. There is no closing time. Submitting at 6 PM,
9 PM, or 11:58 PM are all equally "on time."

work_date (the day the report is ABOUT) and submitted_at (when it was
ACTUALLY submitted) are always stored separately and never conflated — see
README "Performance work date vs submission time". A report is "backdated"
exactly when it was submitted on a later calendar day than the one it's
about; "submitted" when work_date and the submission's calendar day match.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.config import Settings
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_now, get_office_today, localize_time_on_date

DEFAULT_MISSING_LOOKBACK_DAYS = 14
DEFAULT_HISTORY_DAYS = 30


def is_performance_available(settings: Settings, at=None) -> bool:
    """True once office time has reached PERFORMANCE_START_TIME today
    (inclusive — see README section 23's "At 5 PM: Available" example).
    There is no upper bound; this only ever answers "has the window
    opened", never "is it too late"."""
    now = at or get_office_now(settings)
    threshold = localize_time_on_date(settings, now.date(), settings.performance_start_time)
    return now >= threshold


def get_performance_for_date(employee_id: str, work_date: date) -> Optional[Dict[str, Any]]:
    client = get_service_client()
    result = (
        client.table("performance_updates")
        .select("*")
        .eq("employee_id", employee_id)
        .eq("work_date", work_date.isoformat())
        .maybe_single()
        .execute()
    )
    return result.data


def get_today_status(employee_id: str, settings: Settings) -> Dict[str, Any]:
    """
    What the employee should see right now for today's report: whether
    it's not yet available, available-and-unsubmitted, or already
    submitted — plus the underlying record if one exists.
    """
    now = get_office_now(settings)
    today = now.date()
    available_from_dt = localize_time_on_date(settings, today, settings.performance_start_time)
    row = get_performance_for_date(employee_id, today)

    if row and row.get("submitted_at"):
        return {
            "work_date": today.isoformat(),
            "status": row["status"],
            "available_from": available_from_dt.isoformat(),
            "record": row,
        }

    status_val = "available" if is_performance_available(settings, at=now) else "not_available"
    return {
        "work_date": today.isoformat(),
        "status": status_val,
        "available_from": available_from_dt.isoformat(),
        "record": None,
    }


def submit_performance(
    employee_id: str,
    work_date: Optional[date],
    fields: Dict[str, Any],
    settings: Settings,
) -> Dict[str, Any]:
    """
    Create or replace a performance report for a given work_date.

    Allowed dates for a normal self-service submission (README section 29):
      - today, but only once the 5 PM window has opened
      - yesterday, any time (the "update yesterday" missing-performance flow)
      - anything older is rejected — correcting older records requires
        admin authorization, which is intentionally not exposed through
        this endpoint (no self-service path exists to backdate arbitrary
        history).
    """
    now = get_office_now(settings)
    today = now.date()
    target_date = work_date or today

    if target_date > today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid work date.",
        )

    if target_date == today:
        if not is_performance_available(settings, at=now):
            available_from_dt = localize_time_on_date(settings, today, settings.performance_start_time)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Today's performance is available from "
                    f"{available_from_dt.strftime('%I:%M %p').lstrip('0')}."
                ),
            )
    elif target_date == today - timedelta(days=1):
        pass  # yesterday is always allowed, regardless of time of day
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Older performance updates require admin authorization.",
        )

    existing = get_performance_for_date(employee_id, target_date)
    if existing and existing.get("submitted_at"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted performance for this date.",
        )

    computed_status = "submitted" if target_date == today else "backdated"
    available_from_dt = localize_time_on_date(settings, target_date, settings.performance_start_time)

    row_payload = {
        "employee_id": employee_id,
        "work_date": target_date.isoformat(),
        "performance_text": fields.get("performance_text"),
        "completed_tasks": fields.get("completed_tasks"),
        "pending_tasks": fields.get("pending_tasks"),
        "blockers": fields.get("blockers"),
        "additional_notes": fields.get("additional_notes"),
        "status": computed_status,
        "available_from": available_from_dt.isoformat(),
        "submitted_at": now.isoformat(),
    }

    client = get_service_client()
    if existing:
        # A row can exist without submitted_at only in states this service
        # doesn't currently create (rows are only ever inserted here at
        # submission time) — kept as an update path for forward
        # compatibility with a future pre-created "available" row design.
        result = client.table("performance_updates").update(row_payload).eq("id", existing["id"]).execute()
    else:
        try:
            result = client.table("performance_updates").insert(row_payload).execute()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already submitted performance for this date.",
            ) from exc

    return result.data[0]


def get_missing_dates(
    employee_id: str,
    settings: Settings,
    joining_date: Optional[date] = None,
    lookback_days: int = DEFAULT_MISSING_LOOKBACK_DAYS,
) -> List[Dict[str, Any]]:
    """
    Past dates (strictly before today) with no submitted performance
    report, within a lookback window — this powers the post-login "missing
    performance" warning (README section 26-27). Never looks further back
    than the employee's joining_date, and never includes today (today
    isn't "missing" until it becomes yesterday).
    """
    today = get_office_today(settings)
    earliest = today - timedelta(days=lookback_days)
    if joining_date and joining_date > earliest:
        earliest = joining_date

    if earliest >= today:
        return []

    client = get_service_client()
    result = (
        client.table("performance_updates")
        .select("work_date, submitted_at")
        .eq("employee_id", employee_id)
        .gte("work_date", earliest.isoformat())
        .lt("work_date", today.isoformat())
        .execute()
    )
    submitted_dates = {
        row["work_date"] for row in (result.data or []) if row.get("submitted_at")
    }

    missing = []
    d = earliest
    while d < today:
        if d.isoformat() not in submitted_dates:
            missing.append({"work_date": d.isoformat(), "status": "missing"})
        d += timedelta(days=1)
    return missing


def get_history(employee_id: str, settings: Settings, days: int = DEFAULT_HISTORY_DAYS) -> List[Dict[str, Any]]:
    """
    Most-recent-first performance history for the last `days` calendar
    days, synthesizing "missing" (past, unsubmitted) and "available"/
    "not_available" (today, unsubmitted) entries for dates with no row —
    so the employee sees a complete calendar picture, not just their own
    submissions (see README section 30 example, which shows a MISSING row
    even though nothing was ever submitted for that date).
    """
    today = get_office_today(settings)
    start = today - timedelta(days=days - 1)

    client = get_service_client()
    result = (
        client.table("performance_updates")
        .select("*")
        .eq("employee_id", employee_id)
        .gte("work_date", start.isoformat())
        .lte("work_date", today.isoformat())
        .execute()
    )
    rows_by_date = {r["work_date"]: r for r in (result.data or [])}

    history = []
    d = today
    while d >= start:
        key = d.isoformat()
        if key in rows_by_date:
            history.append(rows_by_date[key])
        elif d == today:
            status_val = "available" if is_performance_available(settings) else "not_available"
            history.append({"work_date": key, "status": status_val, "submitted_at": None})
        else:
            history.append({"work_date": key, "status": "missing", "submitted_at": None})
        d -= timedelta(days=1)
    return history
