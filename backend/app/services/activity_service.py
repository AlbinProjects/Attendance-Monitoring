"""
System activity monitoring.

Deliberately NOT "productivity monitoring" — see README "Privacy
requirements" and "Important limitation of browser activity". This only
ever knows whether the browser detected an activity event (mouse/keyboard/
touch/scroll), never what the employee was doing, typing, or looking at.

Only two pieces of state exist:
  - activity_heartbeats: one row per open attendance session, holding just
    the timestamp of the most recent detected activity ("last seen").
  - activity_sessions: summarized COMPLETED inactivity periods, written
    only when a new heartbeat arrives after a gap exceeding the grace
    period — never raw per-event logs.

The 10-minute grace period (README section 32) means: the baseline ("last
seen") only ever moves when a real heartbeat arrives. A gap is measured
against that fixed baseline, whether you ask "how much has been missed so
far" mid-gap (the summary/tail calculation below) or "how much was missed
in total" once activity resumes (the persisted period, written by
record_heartbeat). Both use the same formula:

    counted = max(0, gap_seconds - grace_seconds)

This is what makes README's two worked examples consistent with each
other: querying the *same, still-open* gap at two different times (10 min
in: counted=0; 25 min in: counted=15) is the same formula as three
*separate, closed* gaps (8 min: 0; 20 min: 10; 50 min: 40) — see
tests/test_activity.py for both reproduced exactly.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.config import Settings
from app.services import attendance_service
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_now, get_office_today


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


# -----------------------------------------------------------------------
# Data access
# -----------------------------------------------------------------------

def get_heartbeat_row(attendance_id: str) -> Optional[Dict[str, Any]]:
    client = get_service_client()
    result = (
        client.table("activity_heartbeats")
        .select("*")
        .eq("attendance_id", attendance_id)
        .maybe_single()
        .execute()
    )
    return result.data


def upsert_heartbeat(attendance_id: str, employee_id: str, last_heartbeat_at: datetime) -> None:
    client = get_service_client()
    payload = {
        "attendance_id": attendance_id,
        "employee_id": employee_id,
        "last_heartbeat_at": last_heartbeat_at.isoformat(),
    }
    if get_heartbeat_row(attendance_id):
        client.table("activity_heartbeats").update(payload).eq("attendance_id", attendance_id).execute()
    else:
        client.table("activity_heartbeats").insert(payload).execute()


def create_activity_period(
    attendance_id: str,
    employee_id: str,
    started_at: datetime,
    ended_at: datetime,
    duration_seconds: int,
    counted_duration_seconds: int,
) -> Dict[str, Any]:
    client = get_service_client()
    result = (
        client.table("activity_sessions")
        .insert(
            {
                "attendance_id": attendance_id,
                "employee_id": employee_id,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "duration_seconds": duration_seconds,
                "counted_duration_seconds": counted_duration_seconds,
            }
        )
        .execute()
    )
    return result.data[0]


def get_periods_for_attendance(attendance_id: str) -> List[Dict[str, Any]]:
    client = get_service_client()
    result = (
        client.table("activity_sessions")
        .select("*")
        .eq("attendance_id", attendance_id)
        .execute()
    )
    return result.data or []


# -----------------------------------------------------------------------
# Heartbeat ingestion
# -----------------------------------------------------------------------

def record_heartbeat(employee_id: str, settings: Settings) -> Dict[str, Any]:
    """
    Called by the frontend's throttled heartbeat (README section 34, every
    30-60s while the browser detects activity). Only ever advances the
    "last seen" pointer and, if the gap since the previous heartbeat
    exceeded the grace period, persists exactly one summarized inactivity
    period for that gap.
    """
    today = get_office_today(settings)
    attendance = attendance_service.get_attendance_for_date(employee_id, today)

    if not attendance or not attendance.get("check_in"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must check in before activity can be tracked.",
        )
    if attendance.get("check_out"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Today's attendance session has already ended.",
        )

    now = get_office_now(settings)
    attendance_id = attendance["id"]
    heartbeat_row = get_heartbeat_row(attendance_id)
    last_seen = _parse(heartbeat_row["last_heartbeat_at"]) if heartbeat_row else _parse(attendance["check_in"])

    grace_seconds = settings.inactivity_start_minutes * 60
    gap_seconds = (now - last_seen).total_seconds()

    period_recorded = None
    if gap_seconds > grace_seconds:
        counted_seconds = gap_seconds - grace_seconds
        period_recorded = create_activity_period(
            attendance_id=attendance_id,
            employee_id=employee_id,
            started_at=last_seen,
            ended_at=now,
            duration_seconds=int(gap_seconds),
            counted_duration_seconds=int(counted_seconds),
        )

    upsert_heartbeat(attendance_id, employee_id, now)

    return {"server_time": now.isoformat(), "period_recorded": period_recorded}


# -----------------------------------------------------------------------
# Summary
# -----------------------------------------------------------------------

def get_activity_summary_for_attendance(attendance: Optional[Dict[str, Any]], settings: Settings) -> Dict[str, Any]:
    """
    Full-session activity summary for one attendance record — works
    identically whether the session is still open (uses "now" as the end
    boundary) or already checked out (uses check_out). Reused by both the
    employee's own "today" view and, in Phase 8, the admin per-employee
    activity view — this function takes an already-fetched attendance row
    rather than an employee_id so admin callers can pass any employee's
    record, not just the caller's own.
    """
    if not attendance or not attendance.get("check_in"):
        return {
            "attendance_id": attendance.get("id") if attendance else None,
            "checked_in": False,
            "check_in": None,
            "check_out": None,
            "total_session_seconds": 0,
            "counted_inactivity_seconds": 0,
            "active_session_seconds": 0,
            "flagged": False,
            "periods": [],
        }

    attendance_id = attendance["id"]
    check_in_dt = _parse(attendance["check_in"])
    now = get_office_now(settings)
    end_dt = _parse(attendance["check_out"]) if attendance.get("check_out") else now
    total_seconds = max(0.0, (end_dt - check_in_dt).total_seconds())

    periods = get_periods_for_attendance(attendance_id)
    counted_seconds = float(sum(p["counted_duration_seconds"] for p in periods))

    # The "tail": time since the last heartbeat (or check-in, if no
    # heartbeat ever arrived) up to the end boundary. Not persisted — this
    # is computed fresh every time so it's always correct up to the
    # instant of the query, including for a session that's still open.
    heartbeat_row = get_heartbeat_row(attendance_id)
    last_seen = _parse(heartbeat_row["last_heartbeat_at"]) if heartbeat_row else check_in_dt
    grace_seconds = settings.inactivity_start_minutes * 60
    tail_gap_seconds = max(0.0, (end_dt - last_seen).total_seconds())
    if tail_gap_seconds > grace_seconds:
        counted_seconds += tail_gap_seconds - grace_seconds

    active_seconds = max(0.0, total_seconds - counted_seconds)
    flagged = counted_seconds > settings.daily_inactivity_flag_minutes * 60

    return {
        "attendance_id": attendance_id,
        "checked_in": True,
        "check_in": attendance["check_in"],
        "check_out": attendance.get("check_out"),
        "total_session_seconds": int(total_seconds),
        "counted_inactivity_seconds": int(counted_seconds),
        "active_session_seconds": int(active_seconds),
        "flagged": flagged,
        "periods": periods,
    }


def get_today_activity_summary(employee_id: str, settings: Settings) -> Dict[str, Any]:
    today = get_office_today(settings)
    attendance = attendance_service.get_attendance_for_date(employee_id, today)
    return get_activity_summary_for_attendance(attendance, settings)
