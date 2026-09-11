"""Employee break tracking for checked-in office/WFH sessions."""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.services import audit_service, calendar_service
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_now, get_office_today

BREAK_TYPES = {"tea": "Tea Break", "lunch": "Lunch Break", "evening": "Evening Break"}


def _get_attendance(employee_id: str, on_date: date) -> Optional[Dict[str, Any]]:
    result = (
        get_service_client().table("attendance").select("*")
        .eq("employee_id", employee_id)
        .eq("attendance_date", on_date.isoformat())
        .maybe_single().execute()
    )
    return result.data if result else None


def _get_active_break(attendance_id: str) -> Optional[Dict[str, Any]]:
    result = (
        get_service_client().table("break_sessions").select("*")
        .eq("attendance_id", attendance_id)
        .is_("ended_at", "null")
        .order("started_at", desc=True)
        .limit(1).execute()
    )
    if not result or not result.data:
        return None
    return result.data[0]


def get_breaks_for_attendance(attendance_id: str) -> List[Dict[str, Any]]:
    result = (
        get_service_client().table("break_sessions").select("*")
        .eq("attendance_id", attendance_id)
        .order("started_at", desc=False).execute()
    )
    return (result.data if result else None) or []


def _duration_seconds(row: Dict[str, Any], now) -> int:
    from datetime import datetime
    start = datetime.fromisoformat(row["started_at"])
    end = datetime.fromisoformat(row["ended_at"]) if row.get("ended_at") else now
    return max(0, int((end - start).total_seconds()))


def get_break_summary(attendance_id: str, now=None) -> Dict[str, Any]:
    from app.config import get_settings
    now = now or get_office_now(get_settings())
    sessions = get_breaks_for_attendance(attendance_id)
    total = sum(_duration_seconds(r, now) for r in sessions)
    active = next((r for r in sessions if not r.get("ended_at")), None)
    used_types = {r.get("break_type") for r in sessions if r.get("break_type") in BREAK_TYPES}
    return {
        "total_break_seconds": total,
        "active_break": active,
        "sessions": sessions,
        "used_break_types": sorted(used_types),
        "available_break_types": [t for t in BREAK_TYPES if t not in used_types],
    }


def get_today(employee_id: str) -> Dict[str, Any]:
    from app.config import get_settings
    settings = get_settings()
    today = get_office_today(settings)
    attendance = _get_attendance(employee_id, today)
    if not attendance:
        return {
            "attendance": None,
            "total_break_seconds": 0,
            "active_break": None,
            "sessions": [],
            "used_break_types": [],
            "available_break_types": list(BREAK_TYPES),
        }
    summary = get_break_summary(attendance["id"], get_office_now(settings))
    return {"attendance": attendance, **summary}


def start_break(employee_id: str, break_type: str) -> Dict[str, Any]:
    if break_type not in BREAK_TYPES:
        raise HTTPException(status_code=400, detail="Choose Tea Break, Lunch Break, or Evening Break.")

    from app.config import get_settings
    settings = get_settings()
    now = get_office_now(settings)
    today = get_office_today(settings)
    attendance = _get_attendance(employee_id, today)

    approved_leave = calendar_service.get_leave_for_employee_date(employee_id, today)
    if approved_leave and approved_leave.get("status") == "approved" and approved_leave.get("leave_type") != "half_day":
        leave_label = str(approved_leave.get("leave_type") or "approved").replace("_", " ").title()
        raise HTTPException(status_code=403, detail=f"You are on approved {leave_label} leave today. Breaks are not required.")

    if not attendance or not attendance.get("check_in"):
        raise HTTPException(status_code=400, detail="You must check in before starting a break.")
    if attendance.get("check_out"):
        raise HTTPException(status_code=400, detail="Today's attendance session has already ended.")

    from app.services import remote_work_service, on_duty_service
    remote = remote_work_service.get_today(employee_id)
    on_duty = on_duty_service.get_today(employee_id)
    if (remote and remote.get("work_mode") == "other_site") or on_duty:
        raise HTTPException(status_code=403, detail="Breaks are not tracked for this work mode.")

    active = _get_active_break(attendance["id"])
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"{BREAK_TYPES.get(active.get('break_type'), 'A break')} is already in progress. End it before starting another break.",
        )

    # Each break type may be taken once per attendance day. A completed Tea
    # Break, for example, cannot be started a second time later that day.
    existing = (
        get_service_client().table("break_sessions").select("id,break_type,started_at,ended_at")
        .eq("attendance_id", attendance["id"])
        .eq("break_type", break_type)
        .limit(1).execute()
    )
    if existing and existing.data:
        raise HTTPException(
            status_code=409,
            detail=f"{BREAK_TYPES[break_type]} has already been used today. You can use each break type only once per day.",
        )

    payload = {
        "attendance_id": attendance["id"],
        "employee_id": employee_id,
        "break_type": break_type,
        "started_at": now.isoformat(),
    }
    try:
        result = get_service_client().table("break_sessions").insert(payload).execute()
    except Exception as exc:
        message = str(exc).lower()
        if "one break type per day" in message or "one active break" in message or "uq_break_sessions_one_active_per_attendance" in message:
            raise HTTPException(status_code=409, detail="That break cannot be started because another break of the same type or an active break already exists today.") from exc
        raise HTTPException(status_code=500, detail="Couldn't start break. Please try again.") from exc
    if not result or not result.data:
        raise HTTPException(status_code=500, detail="Couldn't start break. Please try again.")
    row = result.data[0]

    try:
        from app.services import activity_service
        activity_service.upsert_heartbeat(attendance["id"], employee_id, now)
    except Exception:
        pass

    audit_service.write_audit_log(
        action="BREAK_STARTED", employee_id=employee_id, attendance_id=attendance["id"],
        new_value={"break_type": break_type, "started_at": row["started_at"]}, performed_by=employee_id,
    )
    return row


def end_break(employee_id: str) -> Dict[str, Any]:
    from app.config import get_settings
    settings = get_settings()
    now = get_office_now(settings)
    today = get_office_today(settings)
    attendance = _get_attendance(employee_id, today)
    if not attendance:
        raise HTTPException(status_code=400, detail="No attendance session exists for today.")

    active = _get_active_break(attendance["id"])
    if not active:
        raise HTTPException(status_code=400, detail="No active break to end.")

    result = (
        get_service_client().table("break_sessions")
        .update({"ended_at": now.isoformat()})
        .eq("id", active["id"])
        .is_("ended_at", "null")
        .execute()
    )
    if not result or not result.data:
        # Another request may have ended it. Return the current state rather
        # than making the employee reload the page to recover.
        latest = _get_active_break(attendance["id"])
        if latest:
            raise HTTPException(status_code=409, detail="The break is still in progress. Please try ending it again.")
        raise HTTPException(status_code=409, detail="The break was already ended. Refreshing your break status.")
    row = result.data[0]

    try:
        from app.services import activity_service
        activity_service.upsert_heartbeat(attendance["id"], employee_id, now)
    except Exception:
        pass

    audit_service.write_audit_log(
        action="BREAK_ENDED", employee_id=employee_id, attendance_id=attendance["id"],
        old_value={"break_type": active["break_type"], "started_at": active["started_at"], "ended_at": None},
        new_value={"ended_at": row["ended_at"]}, performed_by=employee_id,
    )
    return row
