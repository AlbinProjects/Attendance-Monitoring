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

from datetime import datetime, timedelta
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
    """Return the latest heartbeat row, or None when no heartbeat exists.

    Do not rely on ``maybe_single()`` here. With some supabase-py/client
    combinations, a zero-row maybe-single query can produce a None response
    object, which makes ``result.data`` raise AttributeError. A heartbeat is
    optional, especially immediately after check-in, so a missing row must
    simply be treated as no activity recorded yet.
    """
    client = get_service_client()
    result = (
        client.table("activity_heartbeats")
        .select("*")
        .eq("attendance_id", attendance_id)
        .limit(1)
        .execute()
    )

    if not result or not result.data:
        return None

    return result.data[0]


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
    return (result.data if result else None) or []


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

    # Work From Other Site and On Duty deliberately do not use laptop
    # monitoring. They remain performance-tracked, but no browser activity
    # heartbeat/session data is collected for those work modes.
    from app.services import remote_work_service, on_duty_service
    remote = remote_work_service.get_today(employee_id)
    on_duty = on_duty_service.get_today(employee_id)
    if remote and remote.get("work_mode") == "other_site":
        return {"server_time": get_office_now(settings).isoformat(), "monitoring": False, "reason": "other_site"}
    if on_duty:
        return {"server_time": get_office_now(settings).isoformat(), "monitoring": False, "reason": "on_duty"}

    attendance = attendance_service.get_attendance_for_date(employee_id, today)

    if attendance and attendance.get("check_in"):
        from app.services import break_service
        if break_service._get_active_break(attendance["id"]):
            now = get_office_now(settings)
            upsert_heartbeat(attendance["id"], employee_id, now)
            return {"server_time": now.isoformat(), "monitoring": False, "reason": "break"}

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
    # Advanced desktop monitoring is an optional company-wide feature and is
    # OFF by default. When it is disabled, no inactivity time or flags may be
    # calculated anywhere (dashboard, attendance, or activity drill-downs).
    # Keep this backend-side so the rule cannot be bypassed by calling an API
    # directly.
    from app.services import company_config_service
    if not company_config_service.get_effective_config(settings).advanced_desktop_monitoring_enabled:
        return {
            "attendance_id": attendance.get("id") if attendance else None,
            "checked_in": bool(attendance and attendance.get("check_in")),
            "check_in": attendance.get("check_in") if attendance else None,
            "check_out": attendance.get("check_out") if attendance else None,
            "total_session_seconds": 0,
            "counted_inactivity_seconds": 0,
            "active_session_seconds": 0,
            "flagged": False,
            "periods": [],
            "monitoring": False,
        }

    # These modes intentionally have no laptop monitoring.
    from app.services import remote_work_service, on_duty_service
    employee_id = attendance.get("employee_id") if attendance else None
    if employee_id:
        remote = remote_work_service.get_today(employee_id)
        on_duty = on_duty_service.get_today(employee_id)
        if (remote and remote.get("work_mode") == "other_site") or on_duty:
            return {
                "attendance_id": attendance.get("id") if attendance else None,
                "checked_in": bool(attendance and attendance.get("check_in")),
                "check_in": attendance.get("check_in") if attendance else None,
                "check_out": attendance.get("check_out") if attendance else None,
                "total_session_seconds": 0,
                "counted_inactivity_seconds": 0,
                "active_session_seconds": 0,
                "flagged": False,
                "periods": [],
                "monitoring": False,
            }

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
    if attendance.get("check_out"):
        end_dt = _parse(attendance["check_out"])
    else:
        # Never let an open attendance session run into the next calendar
        # day. Otherwise an employee who forgot to check out yesterday can
        # appear to have 20+ hours of activity/inactivity today.
        next_day = check_in_dt.date() + __import__("datetime").timedelta(days=1)
        end_dt = min(now, datetime.combine(next_day, datetime.min.time(), tzinfo=check_in_dt.tzinfo))
    total_seconds = max(0.0, (end_dt - check_in_dt).total_seconds())

    periods = get_periods_for_attendance(attendance_id)
    counted_seconds = float(sum(p["counted_duration_seconds"] for p in periods))

    from app.services import break_service
    break_summary = break_service.get_break_summary(attendance_id, end_dt)
    break_seconds = float(break_summary["total_break_seconds"])

    # The "tail": time since the last heartbeat (or check-in, if no
    # heartbeat ever arrived) up to the end boundary. Not persisted — this
    # is computed fresh every time so it's always correct up to the
    # instant of the query, including for a session that's still open.
    heartbeat_row = get_heartbeat_row(attendance_id)
    last_seen = _parse(heartbeat_row["last_heartbeat_at"]) if heartbeat_row else check_in_dt
    grace_seconds = settings.inactivity_start_minutes * 60
    tail_gap_seconds = max(0.0, (end_dt - last_seen).total_seconds())
    unavailable_seconds = get_monitoring_unavailable_seconds(attendance_id, last_seen, end_dt)
    countable_tail_seconds = max(0.0, tail_gap_seconds - unavailable_seconds)
    if countable_tail_seconds > grace_seconds:
        counted_seconds += countable_tail_seconds - grace_seconds

    active_seconds = max(0.0, total_seconds - counted_seconds - break_seconds - unavailable_seconds)
    flagged = counted_seconds > settings.daily_inactivity_flag_minutes * 60

    return {
        "attendance_id": attendance_id,
        "checked_in": True,
        "check_in": attendance["check_in"],
        "check_out": attendance.get("check_out"),
        "total_session_seconds": int(total_seconds),
        "counted_inactivity_seconds": int(counted_seconds),
        "active_session_seconds": int(active_seconds),
        "total_break_seconds": int(break_seconds),
        "monitoring_unavailable_seconds": int(unavailable_seconds),
        "active_break": break_summary["active_break"],
        "breaks": break_summary["sessions"],
        "flagged": flagged,
        "periods": periods,
    }


def get_today_activity_summary(employee_id: str, settings: Settings) -> Dict[str, Any]:
    today = get_office_today(settings)
    attendance = attendance_service.get_attendance_for_date(employee_id, today)
    return get_activity_summary_for_attendance(attendance, settings)

# -----------------------------------------------------------------------
# Desktop-agent timestamped events / connectivity resilience
# -----------------------------------------------------------------------

def _attendance_for_event(employee_id: str, event_at: datetime, settings: Settings):
    return attendance_service.get_attendance_for_date(employee_id, event_at.date())


def record_desktop_event(employee_id: str, payload: Dict[str, Any], settings: Settings) -> Dict[str, Any]:
    """Process privacy-safe desktop agent events.

    Events are timestamped by the agent and contain no application name or
    user content. Active events advance the normal last-seen pointer.
    Offline intervals are explicitly recorded as monitoring-unavailable so
    they are never converted into employee inactivity.
    """
    event_type = str(payload.get("event_type") or "active")
    try:
        event_at = _parse(payload.get("event_at"))
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid desktop event timestamp.")
    now = get_office_now(settings)
    if event_at > now + timedelta(minutes=5) or event_at < now - timedelta(days=2):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Desktop event timestamp is outside the allowed window.")
    attendance = _attendance_for_event(employee_id, event_at, settings)
    if not attendance or not attendance.get("check_in"):
        return {"accepted": False, "reason": "no_attendance"}
    if attendance.get("check_out") and event_at > _parse(attendance["check_out"]):
        return {"accepted": False, "reason": "attendance_closed"}

    if event_type == "active":
        upsert_heartbeat(attendance["id"], employee_id, event_at)
        return {"accepted": True, "event_type": "active"}

    if event_type == "monitoring_unavailable":
        started_at = _parse(payload.get("started_at"))
        ended_at = _parse(payload.get("ended_at"))
        if ended_at < started_at:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid monitoring interval.")
        client = get_service_client()
        client.table("monitoring_connectivity_periods").insert({
            "attendance_id": attendance["id"],
            "employee_id": employee_id,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "reason": "network_unavailable",
        }).execute()
        return {"accepted": True, "event_type": event_type}

    return {"accepted": False, "reason": "unsupported_event"}


def get_monitoring_unavailable_seconds(attendance_id: str, start_dt: datetime, end_dt: datetime) -> int:
    client = get_service_client()
    result = client.table("monitoring_connectivity_periods").select("started_at,ended_at").eq("attendance_id", attendance_id).execute()
    total = 0.0
    for row in ((result.data if result else None) or []):
        a = max(start_dt, _parse(row["started_at"]))
        b = min(end_dt, _parse(row["ended_at"]))
        if b > a:
            total += (b - a).total_seconds()
    return int(total)
