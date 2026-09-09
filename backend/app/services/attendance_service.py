"""
Attendance business logic.

Every timestamp used here comes from the SERVER, in the configured office
timezone — never from the client's device clock (see README "Attendance
timezone"). Duplicate check-ins are guarded in two layers: an application-
level pre-check (for a clean error message) and the database's own
`uq_attendance_employee_date` unique constraint (the actual backstop that
makes duplicates impossible even under a race — see
supabase/migrations/001_schema.sql).

Phase 13: check-in/check-out require GPS location verification
(app/services/location_service.py) instead of public-IP allowlisting —
see README "GPS-based attendance verification" for why. The resolved
client IP, if available, is still captured as informational/audit
metadata alongside the location data.

Phase 14: a Super Admin can now choose, per company, whether attendance
ALSO requires an IP allowlist match on top of GPS ("static" network mode,
for companies with a genuine static IP) or GPS alone ("dynamic" mode —
see app/services/company_config_service.py for the DB-over-env
precedence). Check-in additionally requires the employee's laptop to have
pinged recently (app/services/laptop_presence_service.py) — the phone
alone is not enough; the two devices are meant to be used together
throughout the day.
"""

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.config import Settings
from app.services import audit_service, break_service, calendar_service, company_config_service, laptop_presence_service, location_service, network_service, remote_work_service
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_now, get_office_today, localize_time_on_date

# Re-exported here (rather than only in time_service) so existing callers/
# tests that reference attendance_service.get_office_now /
# attendance_service.get_office_today keep working unchanged.
__all__ = [
    "get_office_now",
    "get_office_today",
    "determine_attendance_status",
    "get_attendance_for_date",
    "get_attendance_history",
    "get_monthly_attendance",
    "create_check_in",
    "create_check_out",
]


# Client-facing messages for each way GPS verification can fail — kept
# here (not in location_service) since location_service returns a
# structured, UI-copy-agnostic result and the wording is a router/service
# boundary concern.
_LOCATION_ERROR_MESSAGES = {
    "accuracy_too_low": "Location accuracy is too low. Please enable location services and try again.",
    "outside_radius": "Attendance can only be marked from the permitted office area.",
}

LAPTOP_NOT_CONNECTED_MESSAGE = (
    "Please open the attendance app on your laptop before checking in from your phone."
)
NETWORK_NOT_ALLOWED_MESSAGE = "Attendance can only be marked while connected to the company network."


def determine_attendance_status(check_in_dt: datetime, settings: Settings) -> str:
    """
    "present" if check-in happened at or before office_start_time +
    late_threshold_minutes; "late" if strictly after. Both times are
    compared in the office timezone regardless of where the employee's
    device thinks it is.
    """
    threshold_dt = localize_time_on_date(
        settings, check_in_dt.date(), settings.office_start_time
    ) + timedelta(minutes=settings.late_threshold_minutes)
    return "late" if check_in_dt > threshold_dt else "present"


def get_attendance_for_date(employee_id: str, attendance_date: date) -> Optional[Dict[str, Any]]:
    client = get_service_client()
    result = (
        client.table("attendance")
        .select("*")
        .eq("employee_id", employee_id)
        .eq("attendance_date", attendance_date.isoformat())
        .maybe_single()
        .execute()
    )
    if result is None:
        return None
    return result.data


def get_attendance_history(employee_id: str) -> list:
    """Return the employee attendance history using only stable columns.

    Keep this query deliberately narrow so newer/optional attendance columns
    cannot make the employee history endpoint fail.
    """
    client = get_service_client()
    result = (
        client.table("attendance")
        .select("id,employee_id,attendance_date,check_in,check_out,status,check_in_source,check_out_source,reason,marked_by,created_at,updated_at")
        .eq("employee_id", employee_id)
        .order("attendance_date", desc=True)
        .execute()
    )
    if result is None:
        return []
    rows = result.data or []
    for row in rows:
        try:
            summary = break_service.get_break_summary(row["id"])
            row["total_break_seconds"] = summary["total_break_seconds"]
            row["breaks"] = summary["sessions"]
        except Exception:
            row["total_break_seconds"] = 0
            row["breaks"] = []
    return rows


def get_monthly_attendance(employee_id: str, year: int, month: int, settings: Settings) -> list:
    """Return every calendar date in the requested month with attendance,
    leave, break and eight-hour workday information. Calendar dates are the
    source of truth, so Sundays/holidays are represented even when there is
    no attendance row."""
    from calendar import monthrange
    from datetime import datetime, time as dt_time

    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month.")

    history_start = date(2026, 9, 1)
    start = max(date(year, month, 1), history_start)
    end = date(year, month, monthrange(year, month)[1])
    if end < history_start:
        return []
    client = get_service_client()
    attendance_rows = (client.table("attendance").select(
        "id,employee_id,attendance_date,check_in,check_out,status,check_in_source,check_out_source,reason,marked_by,created_at,updated_at"
    ).eq("employee_id", employee_id).gte("attendance_date", start.isoformat())
      .lte("attendance_date", end.isoformat()).order("attendance_date", desc=False).execute().data or [])
    attendance_by_date = {r["attendance_date"]: r for r in attendance_rows}

    # Fetch all break sessions for the month in one query. This avoids the
    # per-day service calls that could fail independently and leave the UI
    # showing 0m even when break records exist.
    attendance_ids = [r["id"] for r in attendance_rows if r.get("id")]
    breaks_by_attendance = {}
    if attendance_ids:
        break_rows = (client.table("break_sessions")
                      .select("id,attendance_id,employee_id,break_type,started_at,ended_at")
                      .in_("attendance_id", attendance_ids)
                      .order("started_at", desc=False).execute().data or [])
        for br in break_rows:
            breaks_by_attendance.setdefault(br["attendance_id"], []).append(br)

    leave_rows = (client.table("employee_leaves").select("id,leave_date,leave_type,half_day_period,status,is_additional,reason,granted_by")
                  .eq("employee_id", employee_id).gte("leave_date", start.isoformat())
                  .lte("leave_date", end.isoformat()).execute().data or [])
    leave_by_date = {r["leave_date"]: r for r in leave_rows
                     if r.get("status") == "approved"}

    today = get_office_today(settings)
    now = get_office_now(settings)
    # Enforce the 4 PM rule for every elapsed working date in the displayed
    # month. Existing approved leave or attendance always wins, so an admin
    # correction is never overwritten.
    cursor = start
    while cursor <= min(end, today):
        _ensure_auto_unpaid_leave(employee_id, cursor, settings)
        cursor += timedelta(days=1)
    refreshed_leaves = (client.table("employee_leaves").select("id,leave_date,leave_type,half_day_period,status,is_additional,reason,granted_by")
                        .eq("employee_id", employee_id).gte("leave_date", start.isoformat())
                        .lte("leave_date", end.isoformat()).execute().data or [])
    leave_by_date = {r["leave_date"]: r for r in refreshed_leaves if r.get("status") == "approved"}

    out = []
    target_seconds = 8 * 60 * 60
    first_day = max(1, (start - date(year, month, 1)).days + 1)
    for day_num in range(first_day, monthrange(year, month)[1] + 1):
        d = date(year, month, day_num)
        iso = d.isoformat()
        calendar = calendar_service.get_day_status(d)
        leave = leave_by_date.get(iso)
        attendance = attendance_by_date.get(iso)
        breaks = []
        total_break_seconds = 0
        if attendance:
            breaks = list(breaks_by_attendance.get(attendance["id"], []))
            break_now = now if d == today else localize_time_on_date(settings, d + timedelta(days=1), time(0, 0))
            for br in breaks:
                try:
                    started = datetime.fromisoformat(br["started_at"])
                    ended = datetime.fromisoformat(br["ended_at"]) if br.get("ended_at") else break_now
                    total_break_seconds += max(0, int((min(ended, break_now) - started).total_seconds()))
                except Exception:
                    # A malformed break row should not hide valid break rows.
                    continue

        net_work_seconds = None
        work_status = "not_applicable"
        if calendar["is_working_day"] and not leave:
            if attendance and attendance.get("check_in"):
                check_in_dt = datetime.fromisoformat(attendance["check_in"])
                if attendance.get("check_out"):
                    end_dt = datetime.fromisoformat(attendance["check_out"])
                    work_status = "completed"
                elif d == today:
                    end_dt = now
                    work_status = "in_progress"
                else:
                    # A previous day's open punch is never allowed to remain
                    # "in progress" on a later date. From the following day
                    # onward it is explicitly a missed check-out.
                    end_dt = datetime.combine(d + timedelta(days=1), dt_time.min, tzinfo=check_in_dt.tzinfo)
                    work_status = "checkout_missed"
                gross = max(0, int((end_dt - check_in_dt).total_seconds()))
                net_work_seconds = max(0, gross - total_break_seconds)

                # A missing checkout on a previous day must never keep the
                # session running into later dates.  The date boundary above
                # caps elapsed time at midnight; additionally cap the reported
                # net work for an unclosed past-day attendance at the daily
                # 8-hour target.  This prevents an old open punch from turning
                # into 15h/20h/etc. of phantom work while still showing the day
                # as an incomplete checkout.
                if work_status == "checkout_missed":
                    net_work_seconds = min(net_work_seconds, target_seconds)
                if work_status == "completed":
                    work_status = "completed_8h" if net_work_seconds >= target_seconds else "short_8h"
            elif d < today:
                work_status = "absent"
            elif d == today:
                work_status = "not_checked_in"
            else:
                work_status = "upcoming"

        if leave:
            day_status = "leave"
        elif calendar["day_type"] == "sunday":
            day_status = "sunday"
        elif calendar["day_type"] == "holiday":
            day_status = "holiday"
        elif not calendar["is_working_day"]:
            day_status = "other_non_working"
        else:
            day_status = "working_day"

        out.append({
            "date": iso,
            "calendar": calendar,
            "day_status": day_status,
            "leave": leave,
            "attendance": attendance,
            "breaks": breaks,
            "total_break_seconds": total_break_seconds,
            "net_work_seconds": net_work_seconds,
            "target_work_seconds": target_seconds,
            "work_status": work_status,
        })
    return out


def _ensure_auto_unpaid_leave(employee_id: str, target_date: date, settings: Settings) -> None:
    """At/after 4 PM on a working day, automatically mark an employee as
    unpaid leave when they have neither checked in nor been authorized for
    Other Site/On Duty. The record is a normal approved unpaid leave so an
    administrator can cancel/replace it later with a manual correction."""
    client = get_service_client()
    now = get_office_now(settings)
    cutoff = localize_time_on_date(settings, target_date, time(16, 0))
    if target_date > now.date() or now < cutoff or not calendar_service.is_working_day(target_date):
        return
    employee_row = client.table("employees").select("role,is_active,joining_date").eq("id", employee_id).maybe_single().execute()
    if not employee_row or not employee_row.data or not employee_row.data.get("is_active") or employee_row.data.get("role") != "employee":
        return
    joining_date = employee_row.data.get("joining_date")
    if joining_date and target_date < date.fromisoformat(joining_date):
        return
    if get_attendance_for_date(employee_id, target_date):
        return
    existing = calendar_service.get_leave_for_employee_date(employee_id, target_date)
    if existing and existing.get("status") == "approved":
        return

    # Do not auto-mark employees who have an approved Other Site assignment
    # or an approved/started On Duty session, because those modes intentionally
    # do not use normal attendance punches.
    remote = client.table("remote_work_requests").select("work_mode,status").eq("employee_id", employee_id).eq("work_date", target_date.isoformat()).in_("status", ["approved", "assigned", "started"]).limit(1).execute().data or []
    if remote and remote[0].get("work_mode") == "other_site":
        return
    on_duty = client.table("on_duty_requests").select("status").eq("employee_id", employee_id).eq("on_duty_date", target_date.isoformat()).in_("status", ["approved", "started", "completed"]).limit(1).execute().data or []
    if on_duty:
        return

    payload = {
        "employee_id": employee_id,
        "leave_date": target_date.isoformat(),
        "leave_type": "unpaid",
        "status": "approved",
        "is_additional": False,
        "reason": "Auto-marked unpaid leave: no attendance check-in by 4:00 PM.",
        "granted_by": None,
    }
    try:
        client.table("employee_leaves").insert(payload).execute()
    except Exception as exc:
        if "duplicate" not in str(exc).lower() and "unique" not in str(exc).lower():
            raise


def _verify_location_or_raise(
    latitude: float,
    longitude: float,
    accuracy: float,
    config: "company_config_service.EffectiveConfig",
) -> location_service.LocationVerificationResult:
    result = location_service.verify_location(
        latitude,
        longitude,
        accuracy,
        config.office_latitude,
        config.office_longitude,
        config.office_gps_radius_meters,
        config.max_gps_accuracy_meters,
    )
    if not result.verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_LOCATION_ERROR_MESSAGES.get(
                result.reason, "Attendance can only be marked from the permitted office area."
            ),
        )
    return result


def _verify_network_if_static_mode(
    client_ip: Optional[str], config: "company_config_service.EffectiveConfig"
) -> None:
    """Phase 14: only applies when the Super Admin has selected 'static'
    network mode (a company with a genuine static IP). In 'dynamic' mode
    (default — see README "GPS-based attendance verification"), this is a
    no-op and GPS alone is authoritative."""
    if config.network_mode != "static":
        return
    if not client_ip or not network_service.is_ip_allowed(client_ip, config.allowed_ips):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NETWORK_NOT_ALLOWED_MESSAGE)


def create_check_in(
    employee_id: str,
    latitude: float,
    longitude: float,
    accuracy: float,
    settings: Settings,
    client_ip: Optional[str] = None,
) -> Dict[str, Any]:
    """
    GPS-verified check-in (Phase 13), with Phase 14 additions: requires a
    recent laptop presence ping, and — only in 'static' network mode —
    also requires an IP allowlist match alongside GPS. latitude/longitude/
    accuracy come from the employee's phone browser via the Geolocation
    API — untrusted raw input, independently verified server-side. client_ip,
    if resolved by the caller, is stored purely as informational/audit
    metadata except when network_mode is 'static', in which case it's also
    a required condition (see README "Do not delete historical network
    data" and "GPS-based attendance verification").
    """
    today = get_office_today(settings)

    if not calendar_service.is_working_day(today):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Attendance is not required on this non-working day.")

    # Application-level pre-check for a clean, specific error message.
    if get_attendance_for_date(employee_id, today):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already checked in today.",
        )

    config = company_config_service.get_effective_config(settings)
    remote = remote_work_service.get_today(employee_id)

    # Work From Other Site is intentionally not an attendance punch mode.
    # No check-in/check-out, laptop presence, office GPS radius, or laptop
    # activity monitoring is required. Performance updates are still required
    # through the normal performance workflow.
    if remote and remote.get("work_mode") == "other_site":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Check-in and check-out are not required for approved Work From Other Site assignments.",
        )

    # Normal office work and Work From Home both require the laptop presence
    # gate. WFH additionally uses a real phone GPS fix, but does not require
    # the employee to be inside the office radius.
    if not laptop_presence_service.has_recent_presence(
        employee_id, config.laptop_presence_freshness_minutes, settings
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=LAPTOP_NOT_CONNECTED_MESSAGE)

    if not remote:
        _verify_network_if_static_mode(client_ip, config)
    if remote:
        if accuracy is None or accuracy > config.max_gps_accuracy_meters:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Location accuracy is too low. Please enable location services and try again.")
        location = location_service.verify_location(
            latitude, longitude, accuracy,
            config.office_latitude, config.office_longitude,
            10**9, config.max_gps_accuracy_meters
        )
        source = "remote_wfh"
    else:
        location = _verify_location_or_raise(latitude, longitude, accuracy, config)
        source = "gps"

    now = get_office_now(settings)
    cutoff = localize_time_on_date(settings, today, time(16, 0))
    if now >= cutoff:
        _ensure_auto_unpaid_leave(employee_id, today, settings)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Check-in is closed after 4:00 PM. Today is treated as unpaid leave unless an administrator corrects the record.",
        )
    computed_status = determine_attendance_status(now, settings)

    client = get_service_client()
    try:
        result = (
            client.table("attendance")
            .insert(
                {
                    "employee_id": employee_id,
                    "attendance_date": today.isoformat(),
                    "check_in": now.isoformat(),
                    "status": computed_status,
                    "check_in_source": source,
                    "check_in_ip": client_ip,
                    "remote_work_request_id": remote["id"] if remote else None,
                    "work_location": ("Work From Home" if remote and remote["work_mode"] == "wfh" else remote.get("site_name") if remote else None),
                    "check_in_latitude": latitude,
                    "check_in_longitude": longitude,
                    "check_in_accuracy_meters": location.accuracy_meters,
                    "check_in_distance_meters": location.distance_meters,
                }
            )
            .execute()
        )
    except Exception as exc:
        # Backstop for a race between the pre-check above and this insert
        # (e.g. a double-click firing two near-simultaneous requests). The
        # database's unique constraint is what actually prevents the
        # duplicate; we just translate that into a clean 409 here.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already checked in today.",
        ) from exc

    row = result.data[0]
    audit_service.write_audit_log(
        action="CHECK_IN",
        employee_id=employee_id,
        attendance_id=row["id"],
        new_value={
            "check_in": row["check_in"],
            "status": computed_status,
            "location_verified": True,
            "remote_work": bool(remote),
            "work_mode": remote.get("work_mode") if remote else None,
            "distance_meters": location.distance_meters,
            "accuracy_meters": location.accuracy_meters,
            "network_mode": config.network_mode,
        },
        performed_by=employee_id,
        ip_address=client_ip,
    )
    return row


def create_check_out(
    employee_id: str,
    latitude: float,
    longitude: float,
    accuracy: float,
    settings: Settings,
    client_ip: Optional[str] = None,
) -> Dict[str, Any]:
    """GPS-verified check-out — same location/network verification as
    check-in (README section 11), but does NOT re-check laptop presence:
    by check-out time, the day's activity monitoring (Phase 6) already
    depended on genuine laptop use, which is a stronger signal than a
    fresh ping."""
    today = get_office_today(settings)
    existing = get_attendance_for_date(employee_id, today)

    if not existing or not existing.get("check_in"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot check out because today's check-in was not found.",
        )

    if existing.get("check_out"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already checked out today.",
        )

    active_break = break_service._get_active_break(existing["id"])
    if active_break:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please end your active break before checking out.",
        )

    config = company_config_service.get_effective_config(settings)
    remote = remote_work_service.get_today(employee_id)
    if remote and remote.get("work_mode") == "other_site":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Check-in and check-out are not required for approved Work From Other Site assignments.",
        )
    if not remote:
        _verify_network_if_static_mode(client_ip, config)
    if remote:
        if accuracy is None or accuracy > config.max_gps_accuracy_meters:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Location accuracy is too low. Please enable location services and try again.")
        location = location_service.verify_location(latitude, longitude, accuracy, config.office_latitude, config.office_longitude, 10**9, config.max_gps_accuracy_meters)
        source = "remote_wfh"
    else:
        location = _verify_location_or_raise(latitude, longitude, accuracy, config)
        source = "gps"

    now = get_office_now(settings)

    client = get_service_client()
    result = (
        client.table("attendance")
        .update(
            {
                "check_out": now.isoformat(),
                "check_out_source": source,
                "check_out_ip": client_ip,
                "check_out_latitude": latitude,
                "check_out_longitude": longitude,
                "check_out_accuracy_meters": location.accuracy_meters,
                "check_out_distance_meters": location.distance_meters,
            }
        )
        .eq("id", existing["id"])
        .execute()
    )
    row = result.data[0]

    audit_service.write_audit_log(
        action="CHECK_OUT",
        employee_id=employee_id,
        attendance_id=row["id"],
        old_value={"check_out": None},
        new_value={
            "check_out": row["check_out"],
            "location_verified": True,
            "remote_work": bool(remote),
            "work_mode": remote.get("work_mode") if remote else None,
            "distance_meters": location.distance_meters,
            "accuracy_meters": location.accuracy_meters,
            "network_mode": config.network_mode,
        },
        performed_by=employee_id,
        ip_address=client_ip,
    )
    return row


def get_attendance_by_id(attendance_id: str) -> Optional[Dict[str, Any]]:
    client = get_service_client()
    result = client.table("attendance").select("*").eq("id", attendance_id).maybe_single().execute()
    return result.data


def _cancel_auto_unpaid_leave_for_correction(employee_id: str, attendance_date: date, performed_by: str, reason: str) -> None:
    client = get_service_client()
    existing = calendar_service.get_leave_for_employee_date(employee_id, attendance_date)
    if not existing or existing.get("status") != "approved":
        return
    if existing.get("leave_type") != "unpaid" or not str(existing.get("reason") or "").startswith("Auto-marked unpaid leave:"):
        return
    client.table("employee_leaves").update({"status": "cancelled", "granted_by": performed_by}).eq("id", existing["id"]).execute()
    audit_service.write_audit_log(
        action="LEAVE_CANCELLED", employee_id=employee_id,
        old_value={"status": "approved", "leave_type": "unpaid", "reason": existing.get("reason")},
        new_value={"status": "cancelled"}, performed_by=performed_by, reason=reason,
    )


def create_manual_attendance(
    *,
    employee_id: str,
    attendance_date: date,
    check_in_time: Optional[time],
    check_out_time: Optional[time],
    reason: str,
    marked_by_employee_id: str,
    ip_address: Optional[str],
    settings: Settings,
) -> Dict[str, Any]:
    """
    Admin-only exceptional attendance (README section 19 — WiFi outage,
    forgotten check-in, other authorized case). Unlike the normal
    check-in/check-out flow, the admin's supplied time-of-day IS trusted
    here — that is the entire point of this endpoint — but it is always
    combined with the office timezone server-side (never taken as a raw
    client timestamp), and every write is audited with who, when, and why.
    """
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A reason is required for manual attendance.",
        )
    if check_out_time and not check_in_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A check-out time requires a check-in time.",
        )

    if get_attendance_for_date(employee_id, attendance_date):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance already exists for this date. Use the correction endpoint to update it.",
        )

    check_in_dt = localize_time_on_date(settings, attendance_date, check_in_time) if check_in_time else None
    check_out_dt = localize_time_on_date(settings, attendance_date, check_out_time) if check_out_time else None

    payload = {
        "employee_id": employee_id,
        "attendance_date": attendance_date.isoformat(),
        "check_in": check_in_dt.isoformat() if check_in_dt else None,
        "check_out": check_out_dt.isoformat() if check_out_dt else None,
        "status": "manual",
        "check_in_source": "admin" if check_in_dt else None,
        "check_out_source": "admin" if check_out_dt else None,
        "marked_by": marked_by_employee_id,
        "reason": reason.strip(),
    }

    client = get_service_client()
    try:
        result = client.table("attendance").insert(payload).execute()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Attendance already exists for this date.",
        ) from exc

    row = result.data[0]
    _cancel_auto_unpaid_leave_for_correction(employee_id, attendance_date, marked_by_employee_id, reason.strip())
    audit_service.write_audit_log(
        action="ADMIN_ATTENDANCE_CREATED",
        employee_id=employee_id,
        attendance_id=row["id"],
        new_value=payload,
        performed_by=marked_by_employee_id,
        reason=reason.strip(),
        ip_address=ip_address,
    )
    return row


def update_attendance_by_id(
    *,
    attendance_id: str,
    check_in_time: Optional[time],
    check_out_time: Optional[time],
    reason: str,
    performed_by_employee_id: str,
    ip_address: Optional[str],
    settings: Settings,
) -> Dict[str, Any]:
    """
    Admin correction of an existing attendance record — README section
    11's "Correct attendance when authorized". History is never silently
    overwritten: the prior check_in/check_out/status/reason are captured
    as old_value in the audit log alongside the new values, and a reason
    is mandatory for every correction, not just first-time manual entries.
    """
    if not reason or not reason.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A reason is required to correct attendance.",
        )

    existing = get_attendance_by_id(attendance_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found.")

    attendance_date = date.fromisoformat(existing["attendance_date"])

    new_check_in_dt = localize_time_on_date(settings, attendance_date, check_in_time) if check_in_time else None
    new_check_out_dt = localize_time_on_date(settings, attendance_date, check_out_time) if check_out_time else None

    # Only the fields actually supplied are overwritten; anything omitted
    # keeps its existing value (a correction to just the check-out time
    # shouldn't require re-specifying check-in).
    final_check_in = new_check_in_dt.isoformat() if new_check_in_dt else existing.get("check_in")
    final_check_out = new_check_out_dt.isoformat() if new_check_out_dt else existing.get("check_out")

    if final_check_out and not final_check_in:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A check-out time requires a check-in time.",
        )

    old_value = {
        "check_in": existing.get("check_in"),
        "check_out": existing.get("check_out"),
        "status": existing.get("status"),
        "reason": existing.get("reason"),
    }

    update_fields: Dict[str, Any] = {
        "check_in": final_check_in,
        "check_out": final_check_out,
        "status": "manual",
        "reason": reason.strip(),
        "marked_by": performed_by_employee_id,
    }
    if check_in_time:
        update_fields["check_in_source"] = "admin"
    if check_out_time:
        update_fields["check_out_source"] = "admin"

    client = get_service_client()
    result = client.table("attendance").update(update_fields).eq("id", attendance_id).execute()
    row = result.data[0]
    _cancel_auto_unpaid_leave_for_correction(employee_id, attendance_date, performed_by_employee_id, reason.strip())

    audit_service.write_audit_log(
        action="ADMIN_ATTENDANCE_UPDATED",
        employee_id=existing["employee_id"],
        attendance_id=attendance_id,
        old_value=old_value,
        new_value=update_fields,
        performed_by=performed_by_employee_id,
        reason=reason.strip(),
        ip_address=ip_address,
    )
    return row
