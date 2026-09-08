"""Work From Home / Other Site requests, approvals and assignments."""
from datetime import date, datetime, time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.services import audit_service
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_now, get_office_today, localize_time_on_date
from app.services.calendar_service import is_working_day

WORK_MODES = {"wfh", "other_site"}


def _role(employee_id: str) -> str:
    result = get_service_client().table("employees").select("role,is_active").eq("id", employee_id).maybe_single().execute()
    if result is None or not result.data or not result.data.get("is_active"):
        raise HTTPException(status_code=403, detail="Active employee account required.")
    return result.data["role"]


def _employee(employee_id: str) -> Dict[str, Any]:
    result = get_service_client().table("employees").select("id,name,employee_code,role,is_active").eq("id", employee_id).maybe_single().execute()
    if result is None or not result.data or not result.data.get("is_active"):
        raise HTTPException(status_code=404, detail="Employee not found or inactive.")
    return result.data


def _cutoff(row: Dict[str, Any]) -> datetime:
    # A planned start is the exact cutoff; without a time, the beginning of the requested date is the cutoff.
    from app.config import get_settings
    d = date.fromisoformat(row["work_date"])
    start = time.fromisoformat(row["planned_start"]) if row.get("planned_start") else time.min
    return localize_time_on_date(get_settings(), d, start)


def _ensure_before_start(row: Dict[str, Any]) -> None:
    if get_office_now(__import__("app.config", fromlist=["get_settings"]).get_settings()) >= _cutoff(row):
        raise HTTPException(status_code=409, detail="This request can no longer be changed because its requested date/time has started.")


def _conflicts(employee_id: str, work_date: date, ignore_id: Optional[str] = None) -> None:
    client = get_service_client()
    for table, date_col, label in [("employee_leaves", "leave_date", "leave"), ("on_duty_requests", "on_duty_date", "On Duty"), ("remote_work_requests", "work_date", "remote work")]:
        q = client.table(table).select("id,status").eq("employee_id", employee_id).eq(date_col, work_date.isoformat()).in_("status", ["pending", "approved", "assigned", "started"])
        result = q.execute()
        rows = result.data or []
        if ignore_id:
            rows = [r for r in rows if r.get("id") != ignore_id]
        if rows:
            raise HTTPException(status_code=409, detail=f"An existing {label} request/assignment already exists for this date.")


def _validate_common(employee_id: str, work_mode: str, work_date: date, purpose: str,
                     planned_start: Optional[time], planned_end: Optional[time], site_name: Optional[str]) -> None:
    if work_mode not in WORK_MODES:
        raise HTTPException(status_code=400, detail="Invalid remote work type.")
    if not purpose or not purpose.strip():
        raise HTTPException(status_code=400, detail="A reason/purpose is required.")
    if not is_working_day(work_date):
        raise HTTPException(status_code=400, detail="Remote work can only be requested for a company working day.")
    if planned_end and not planned_start:
        raise HTTPException(status_code=400, detail="A planned end time requires a planned start time.")
    if planned_start and planned_end and planned_end <= planned_start:
        raise HTTPException(status_code=400, detail="Planned end time must be after planned start time.")
    if work_mode == "other_site" and not (site_name or "").strip():
        raise HTTPException(status_code=400, detail="A site name/location is required for Other Site work.")


def request(employee_id: str, work_mode: str, work_date: date, purpose: str,
            planned_start: Optional[time], planned_end: Optional[time], site_name: Optional[str]) -> Dict[str, Any]:
    role = _role(employee_id)
    if role not in {"employee", "admin"}:
        raise HTTPException(status_code=403, detail="Super Admin does not need to request remote work.")
    _validate_common(employee_id, work_mode, work_date, purpose, planned_start, planned_end, site_name)
    _conflicts(employee_id, work_date)
    payload = {
        "employee_id": employee_id, "work_mode": work_mode, "work_date": work_date.isoformat(),
        "purpose": purpose.strip(), "site_name": (site_name or "").strip() or None,
        "planned_start": planned_start.isoformat() if planned_start else None,
        "planned_end": planned_end.isoformat() if planned_end else None,
        "status": "pending", "assignment_source": "requested"
    }
    row = get_service_client().table("remote_work_requests").insert(payload).execute().data[0]
    audit_service.write_audit_log(action="REMOTE_WORK_REQUESTED", employee_id=employee_id, new_value=payload, performed_by=employee_id, reason=purpose.strip())
    return row


def get_my(employee_id: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    _expire_pending_for_employee(employee_id)
    q = get_service_client().table("remote_work_requests").select("*").eq("employee_id", employee_id).order("work_date", desc=True)
    if status_filter:
        q = q.eq("status", status_filter)
    return q.execute().data or []


def _expire_pending_for_employee(employee_id: Optional[str] = None) -> None:
    client = get_service_client()
    q = client.table("remote_work_requests").select("*").eq("status", "pending")
    if employee_id:
        q = q.eq("employee_id", employee_id)
    rows = q.execute().data or []
    now = get_office_now(__import__("app.config", fromlist=["get_settings"]).get_settings())
    for row in rows:
        if now >= _cutoff(row):
            client.table("remote_work_requests").update({"status": "not_approved", "approval_reason": "Approval was not completed before the requested date/time."}).eq("id", row["id"]).execute()
            audit_service.write_audit_log(action="REMOTE_WORK_NOT_APPROVED", employee_id=row["employee_id"], old_value={"status": "pending"}, new_value={"status": "not_approved"}, performed_by=row["employee_id"], reason="Approval deadline passed.")


def get_pending() -> List[Dict[str, Any]]:
    _expire_pending_for_employee()
    return get_service_client().table("remote_work_requests").select("*").eq("status", "pending").order("work_date").execute().data or []


def get_today(employee_id: str) -> Optional[Dict[str, Any]]:
    _expire_pending_for_employee(employee_id)
    today = get_office_today(__import__("app.config", fromlist=["get_settings"]).get_settings())
    result = get_service_client().table("remote_work_requests").select("*").eq("employee_id", employee_id).eq("work_date", today.isoformat()).in_("status", ["approved", "assigned", "started"]).maybe_single().execute()
    return result.data if result is not None else None


def _validate_approver(approver_id: str, target_id: str) -> str:
    actor = _role(approver_id)
    if actor not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Only Admin or Super Admin can approve remote work.")
    target = _employee(target_id)
    if target["role"] == "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin profiles do not need remote work approval.")
    if target["role"] == "admin" and actor != "super_admin":
        raise HTTPException(status_code=403, detail="Only Super Admin can approve an Admin's remote work request.")
    return actor


def approve(request_id: str, approved_by: str) -> Dict[str, Any]:
    client = get_service_client(); result = client.table("remote_work_requests").select("*").eq("id", request_id).maybe_single().execute()
    if result is None or not result.data: raise HTTPException(status_code=404, detail="Remote work request not found.")
    row = result.data
    if row["status"] != "pending": raise HTTPException(status_code=400, detail="Only pending requests can be approved.")
    _validate_approver(approved_by, row["employee_id"])
    _ensure_before_start(row)
    if not is_working_day(date.fromisoformat(row["work_date"])): raise HTTPException(status_code=400, detail="This date is a company non-working day.")
    updated = client.table("remote_work_requests").update({"status": "approved", "approved_by": approved_by, "approval_reason": None}).eq("id", request_id).execute().data[0]
    audit_service.write_audit_log(action="REMOTE_WORK_APPROVED", employee_id=row["employee_id"], old_value={"status":"pending"}, new_value={"status":"approved","approved_by":approved_by}, performed_by=approved_by)
    return updated


def reject(request_id: str, rejected_by: str, reason: Optional[str]) -> Dict[str, Any]:
    client = get_service_client(); result = client.table("remote_work_requests").select("*").eq("id", request_id).maybe_single().execute()
    if result is None or not result.data: raise HTTPException(status_code=404, detail="Remote work request not found.")
    row = result.data
    if row["status"] != "pending": raise HTTPException(status_code=400, detail="Only pending requests can be rejected.")
    _validate_approver(rejected_by, row["employee_id"]); _ensure_before_start(row)
    updated = client.table("remote_work_requests").update({"status":"rejected","approved_by":rejected_by,"approval_reason":reason}).eq("id",request_id).execute().data[0]
    audit_service.write_audit_log(action="REMOTE_WORK_REJECTED", employee_id=row["employee_id"], old_value={"status":"pending"}, new_value={"status":"rejected"}, performed_by=rejected_by, reason=reason)
    return updated


def direct_assign(employee_id: str, work_mode: str, work_date: date, purpose: str,
                  planned_start: Optional[time], planned_end: Optional[time], site_name: Optional[str], assigned_by: str) -> Dict[str, Any]:
    actor = _role(assigned_by)
    if actor not in {"admin", "super_admin"}: raise HTTPException(status_code=403, detail="Only Admin or Super Admin can assign remote work.")
    target = _employee(employee_id)
    if target["role"] == "super_admin": raise HTTPException(status_code=403, detail="Super Admin does not need remote work assignments.")
    if actor == "admin" and target["role"] == "admin": raise HTTPException(status_code=403, detail="Only Super Admin can assign remote work to an Admin.")
    _validate_common(employee_id, work_mode, work_date, purpose, planned_start, planned_end, site_name)
    _ensure_future_for_assignment(work_date, planned_start)
    _conflicts(employee_id, work_date)
    payload = {"employee_id":employee_id,"work_mode":work_mode,"work_date":work_date.isoformat(),"purpose":purpose.strip(),"site_name":(site_name or "").strip() or None,"planned_start":planned_start.isoformat() if planned_start else None,"planned_end":planned_end.isoformat() if planned_end else None,"status":"assigned","approved_by":assigned_by,"assignment_source":"admin_assigned"}
    row = get_service_client().table("remote_work_requests").insert(payload).execute().data[0]
    audit_service.write_audit_log(action="REMOTE_WORK_ASSIGNED", employee_id=employee_id, new_value=payload, performed_by=assigned_by, reason=purpose.strip())
    return row


def _ensure_future_for_assignment(work_date: date, planned_start: Optional[time]) -> None:
    from app.config import get_settings
    cutoff = localize_time_on_date(get_settings(), work_date, planned_start or time.min)
    if get_office_now(get_settings()) >= cutoff:
        raise HTTPException(status_code=409, detail="The assignment must be made before its requested date/time starts.")


def edit(request_id: str, actor_id: str, work_mode: str, work_date: date, purpose: str,
         planned_start: Optional[time], planned_end: Optional[time], site_name: Optional[str]) -> Dict[str, Any]:
    client = get_service_client(); result = client.table("remote_work_requests").select("*").eq("id",request_id).maybe_single().execute()
    if result is None or not result.data: raise HTTPException(status_code=404, detail="Remote work request not found.")
    existing = result.data; actor = _role(actor_id)
    _ensure_before_start(existing)
    if existing["status"] not in {"pending","approved","assigned"}: raise HTTPException(status_code=400, detail="This remote work request can no longer be changed.")
    if actor_id != existing["employee_id"] and actor not in {"admin","super_admin"}: raise HTTPException(status_code=403, detail="Not allowed to edit this request.")
    target = _employee(existing["employee_id"])
    if actor == "admin" and target["role"] == "admin" and actor_id != existing["employee_id"]: raise HTTPException(status_code=403, detail="Only Super Admin can change another Admin's remote work.")
    _validate_common(existing["employee_id"], work_mode, work_date, purpose, planned_start, planned_end, site_name)
    _ensure_future_for_assignment(work_date, planned_start)
    _conflicts(existing["employee_id"], work_date, request_id)
    new_status = existing["status"]
    if actor_id == existing["employee_id"] and existing["status"] == "approved":
        new_status = "pending"
    update = {"work_mode":work_mode,"work_date":work_date.isoformat(),"purpose":purpose.strip(),"site_name":(site_name or "").strip() or None,"planned_start":planned_start.isoformat() if planned_start else None,"planned_end":planned_end.isoformat() if planned_end else None,"status":new_status}
    if new_status == "pending": update.update({"approved_by":None,"approval_reason":None,"assignment_source":"requested"})
    row = client.table("remote_work_requests").update(update).eq("id",request_id).execute().data[0]
    audit_service.write_audit_log(action="REMOTE_WORK_UPDATED", employee_id=existing["employee_id"], old_value=existing, new_value=update, performed_by=actor_id, reason="Remote work details updated before start.")
    return row


def cancel(request_id: str, actor_id: str) -> Dict[str, Any]:
    client = get_service_client(); result = client.table("remote_work_requests").select("*").eq("id",request_id).maybe_single().execute()
    if result is None or not result.data: raise HTTPException(status_code=404, detail="Remote work request not found.")
    row = result.data; actor = _role(actor_id); _ensure_before_start(row)
    if row["status"] not in {"pending","approved","assigned"}: raise HTTPException(status_code=400, detail="This request cannot be cancelled.")
    if actor_id != row["employee_id"] and actor not in {"admin","super_admin"}: raise HTTPException(status_code=403, detail="Not allowed to cancel this request.")
    updated = client.table("remote_work_requests").update({"status":"cancelled"}).eq("id",request_id).execute().data[0]
    audit_service.write_audit_log(action="REMOTE_WORK_CANCELLED", employee_id=row["employee_id"], old_value={"status":row["status"]}, new_value={"status":"cancelled"}, performed_by=actor_id)
    return updated
