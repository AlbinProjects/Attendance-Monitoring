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
from app.services import audit_service, company_config_service, laptop_presence_service, location_service, network_service
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
    return result.data


def get_attendance_history(employee_id: str) -> list:
    client = get_service_client()
    result = (
        client.table("attendance")
        .select("*")
        .eq("employee_id", employee_id)
        .order("attendance_date", desc=True)
        .execute()
    )
    return result.data or []


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

    # Application-level pre-check for a clean, specific error message.
    if get_attendance_for_date(employee_id, today):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already checked in today.",
        )

    config = company_config_service.get_effective_config(settings)

    if not laptop_presence_service.has_recent_presence(
        employee_id, config.laptop_presence_freshness_minutes, settings
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=LAPTOP_NOT_CONNECTED_MESSAGE)

    _verify_network_if_static_mode(client_ip, config)
    location = _verify_location_or_raise(latitude, longitude, accuracy, config)

    now = get_office_now(settings)
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
                    "check_in_source": "gps",
                    "check_in_ip": client_ip,
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

    config = company_config_service.get_effective_config(settings)
    _verify_network_if_static_mode(client_ip, config)
    location = _verify_location_or_raise(latitude, longitude, accuracy, config)

    now = get_office_now(settings)

    client = get_service_client()
    result = (
        client.table("attendance")
        .update(
            {
                "check_out": now.isoformat(),
                "check_out_source": "gps",
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
