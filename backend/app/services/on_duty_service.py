"""On-duty request, approval, and time tracking business logic."""
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.services import audit_service
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_now, get_office_today, localize_time_on_date
from app.services.calendar_service import is_working_day


def _actor_role(employee_id: str) -> str:
    result = (get_service_client().table("employees").select("role,is_active")
              .eq("id", employee_id).maybe_single().execute())
    if result is None or not result.data or not result.data.get("is_active"):
        raise HTTPException(status_code=403, detail="Active employee account required.")
    return result.data["role"]


def _employee(employee_id: str) -> Dict[str, Any]:
    result = (get_service_client().table("employees").select("id,name,employee_code,role,is_active")
              .eq("id", employee_id).maybe_single().execute())
    if result is None or not result.data or not result.data.get("is_active"):
        raise HTTPException(status_code=404, detail="Employee not found or inactive.")
    return result.data


def _check_conflicts(employee_id: str, on_duty_date: date) -> None:
    client = get_service_client()
    leave = (client.table("employee_leaves").select("id,status,leave_type")
             .eq("employee_id", employee_id).eq("leave_date", on_duty_date.isoformat())
             .in_("status", ["pending", "approved"]).maybe_single().execute())
    if leave is not None and leave.data:
        raise HTTPException(status_code=409, detail="A leave request already exists for this date.")

    existing = (client.table("on_duty_requests").select("id,status")
                .eq("employee_id", employee_id).eq("on_duty_date", on_duty_date.isoformat())
                .in_("status", ["pending", "approved"]).maybe_single().execute())
    if existing is not None and existing.data:
        raise HTTPException(status_code=409, detail="An On Duty request already exists for this date.")


def request_on_duty(employee_id: str, on_duty_date: date, purpose: str,
                    planned_start: Optional[time], planned_end: Optional[time]) -> Dict[str, Any]:
    role = _actor_role(employee_id)
    if role not in {"employee", "admin"}:
        raise HTTPException(status_code=403, detail="Super Admin does not need an On Duty request.")
    if not purpose or not purpose.strip():
        raise HTTPException(status_code=400, detail="A purpose is required for On Duty.")
    if not is_working_day(on_duty_date):
        raise HTTPException(status_code=400, detail="On Duty can only be requested for a company working day.")
    if planned_end and not planned_start:
        raise HTTPException(status_code=400, detail="A planned end time requires a planned start time.")
    if planned_start and planned_end and planned_end <= planned_start:
        raise HTTPException(status_code=400, detail="Planned end time must be after planned start time.")
    _check_conflicts(employee_id, on_duty_date)

    payload = {
        "employee_id": employee_id,
        "on_duty_date": on_duty_date.isoformat(),
        "purpose": purpose.strip(),
        "planned_start": planned_start.isoformat() if planned_start else None,
        "planned_end": planned_end.isoformat() if planned_end else None,
        "status": "pending",
    }
    row = get_service_client().table("on_duty_requests").insert(payload).execute().data[0]
    audit_service.write_audit_log(action="ON_DUTY_REQUESTED", employee_id=employee_id,
                                  new_value=payload, performed_by=employee_id, reason=purpose.strip())
    return row


def _validate_approver(approver_id: str, target_id: str) -> str:
    actor_role = _actor_role(approver_id)
    if actor_role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Only Admin or Super Admin can approve On Duty requests.")
    target = _employee(target_id)
    if target["role"] == "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin profiles cannot have On Duty requests.")
    if target["role"] == "admin" and actor_role != "super_admin":
        raise HTTPException(status_code=403, detail="Only Super Admin can approve an Admin's On Duty request.")
    return actor_role


def approve(request_id: str, approved_by: str) -> Dict[str, Any]:
    client = get_service_client()
    result = client.table("on_duty_requests").select("*").eq("id", request_id).maybe_single().execute()
    if result is None or not result.data:
        raise HTTPException(status_code=404, detail="On Duty request not found.")
    existing = result.data
    if existing["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending On Duty requests can be approved.")
    _validate_approver(approved_by, existing["employee_id"])
    if not is_working_day(date.fromisoformat(existing["on_duty_date"])):
        raise HTTPException(status_code=400, detail="This date is a company non-working day.")
    row = client.table("on_duty_requests").update({"status": "approved", "approved_by": approved_by}).eq("id", request_id).execute().data[0]
    audit_service.write_audit_log(action="ON_DUTY_APPROVED", employee_id=existing["employee_id"],
                                  old_value={"status": "pending"},
                                  new_value={"status": "approved", "approved_by": approved_by}, performed_by=approved_by)
    return row


def reject(request_id: str, rejected_by: str, reason: Optional[str]) -> Dict[str, Any]:
    client = get_service_client()
    result = client.table("on_duty_requests").select("*").eq("id", request_id).maybe_single().execute()
    if result is None or not result.data:
        raise HTTPException(status_code=404, detail="On Duty request not found.")
    existing = result.data
    if existing["status"] != "pending":
        raise HTTPException(status_code=400, detail="Only pending On Duty requests can be rejected.")
    _validate_approver(rejected_by, existing["employee_id"])
    row = client.table("on_duty_requests").update({"status": "rejected", "approved_by": rejected_by, "approval_reason": reason}).eq("id", request_id).execute().data[0]
    audit_service.write_audit_log(action="ON_DUTY_REJECTED", employee_id=existing["employee_id"],
                                  old_value={"status": "pending"}, new_value={"status": "rejected"},
                                  performed_by=rejected_by, reason=reason)
    return row


def get_my_requests(employee_id: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    query = get_service_client().table("on_duty_requests").select("*").eq("employee_id", employee_id).order("on_duty_date", desc=True)
    if status_filter:
        query = query.eq("status", status_filter)
    result = query.execute()
    return result.data or []


def get_pending() -> List[Dict[str, Any]]:
    result = get_service_client().table("on_duty_requests").select("*").eq("status", "pending").order("on_duty_date").execute()
    return result.data or []


def get_today(employee_id: str) -> Optional[Dict[str, Any]]:
    today = get_office_today(__import__("app.config", fromlist=["get_settings"]).get_settings())
    result = (get_service_client().table("on_duty_requests").select("*")
              .eq("employee_id", employee_id).eq("on_duty_date", today.isoformat())
              .in_("status", ["approved", "started"]).maybe_single().execute())
    if result is None or not result.data:
        return None
    return result.data


def start_today(employee_id: str) -> Dict[str, Any]:
    role = _actor_role(employee_id)
    if role == "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin does not need On Duty time tracking.")
    row = get_today(employee_id)
    if not row:
        raise HTTPException(status_code=400, detail="No approved On Duty assignment exists for today.")
    if row["status"] == "started" and row.get("started_at"):
        return row
    now = get_office_now(__import__("app.config", fromlist=["get_settings"]).get_settings())
    updated = get_service_client().table("on_duty_requests").update({"status": "started", "started_at": now.isoformat()}).eq("id", row["id"]).execute().data[0]
    audit_service.write_audit_log(action="ON_DUTY_STARTED", employee_id=employee_id,
                                  new_value={"started_at": updated.get("started_at")}, performed_by=employee_id)
    return updated


def end_today(employee_id: str) -> Dict[str, Any]:
    row = get_today(employee_id)
    if not row or row["status"] != "started" or not row.get("started_at"):
        raise HTTPException(status_code=400, detail="You do not have an active On Duty session today.")
    now = get_office_now(__import__("app.config", fromlist=["get_settings"]).get_settings())
    updated = get_service_client().table("on_duty_requests").update({"status": "completed", "ended_at": now.isoformat()}).eq("id", row["id"]).execute().data[0]
    audit_service.write_audit_log(action="ON_DUTY_ENDED", employee_id=employee_id,
                                  new_value={"ended_at": updated.get("ended_at")}, performed_by=employee_id)
    return updated


def direct_grant(employee_id: str, on_duty_date: date, purpose: str,
                 planned_start: Optional[time], planned_end: Optional[time], granted_by: str) -> Dict[str, Any]:
    if _actor_role(granted_by) != "super_admin":
        raise HTTPException(status_code=403, detail="Only Super Admin can directly mark On Duty.")
    _employee(employee_id)
    if not purpose or not purpose.strip():
        raise HTTPException(status_code=400, detail="A purpose is required for On Duty.")
    if not is_working_day(on_duty_date):
        raise HTTPException(status_code=400, detail="On Duty can only be marked for a company working day.")
    _check_conflicts(employee_id, on_duty_date)
    payload = {"employee_id": employee_id, "on_duty_date": on_duty_date.isoformat(),
               "purpose": purpose.strip(), "planned_start": planned_start.isoformat() if planned_start else None,
               "planned_end": planned_end.isoformat() if planned_end else None,
               "status": "approved", "approved_by": granted_by}
    row = get_service_client().table("on_duty_requests").insert(payload).execute().data[0]
    audit_service.write_audit_log(action="ON_DUTY_DIRECT_GRANTED", employee_id=employee_id,
                                  new_value=payload, performed_by=granted_by, reason=purpose.strip())
    return row
