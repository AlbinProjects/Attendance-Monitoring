"""Employee break tracking for checked-in office/WFH sessions."""
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.services import audit_service
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
    now = now or get_office_now(__import__("app.config", fromlist=["get_settings"]).get_settings())
    sessions = get_breaks_for_attendance(attendance_id)
    total = sum(_duration_seconds(r, now) for r in sessions)
    active = next((r for r in sessions if not r.get("ended_at")), None)
    return {
        "total_break_seconds": total,
        "active_break": active,
        "sessions": sessions,
    }


def get_today(employee_id: str) -> Dict[str, Any]:
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    today = get_office_today(settings)
    attendance = _get_attendance(employee_id, today)
    if not attendance:
        return {"attendance": None, "total_break_seconds": 0, "active_break": None, "sessions": []}
    summary = get_break_summary(attendance["id"], get_office_now(settings))
    return {"attendance": attendance, **summary}


def start_break(employee_id: str, break_type: str) -> Dict[str, Any]:
    if break_type not in BREAK_TYPES:
        raise HTTPException(status_code=400, detail="Choose Tea Break, Lunch Break, or Evening Break.")

    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    now = get_office_now(settings)
    today = get_office_today(settings)
    attendance = _get_attendance(employee_id, today)

    if not attendance or not attendance.get("check_in"):
        raise HTTPException(status_code=400, detail="You must check in before starting a break.")
    if attendance.get("check_out"):
        raise HTTPException(status_code=400, detail="Today's attendance session has already ended.")

    # Break tracking is only meaningful for normal attendance sessions.
    from app.services import remote_work_service, on_duty_service
    remote = remote_work_service.get_today(employee_id)
    on_duty = on_duty_service.get_today(employee_id)
    if (remote and remote.get("work_mode") == "other_site") or on_duty:
        raise HTTPException(status_code=403, detail="Breaks are not tracked for this work mode.")

    if _get_active_break(attendance["id"]):
        raise HTTPException(status_code=409, detail="A break is already in progress. End it before starting another break.")

    payload = {
        "attendance_id": attendance["id"],
        "employee_id": employee_id,
        "break_type": break_type,
        "started_at": now.isoformat(),
    }
    row = get_service_client().table("break_sessions").insert(payload).execute().data[0]

    # Reset the activity baseline so break time is never counted as laptop inactivity.
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
    settings = __import__("app.config", fromlist=["get_settings"]).get_settings()
    now = get_office_now(settings)
    today = get_office_today(settings)
    attendance = _get_attendance(employee_id, today)
    if not attendance:
        raise HTTPException(status_code=400, detail="No attendance session exists for today.")

    active = _get_active_break(attendance["id"])
    if not active:
        raise HTTPException(status_code=400, detail="No active break to end.")

    row = get_service_client().table("break_sessions").update({"ended_at": now.isoformat()}).eq("id", active["id"]).execute().data[0]

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
