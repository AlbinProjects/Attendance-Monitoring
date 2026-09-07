"""Company calendar and leave business logic."""
from calendar import monthrange
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.services import audit_service
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_today
from app.config import get_settings

VALID_DAY_TYPES = {"working_day", "sunday", "holiday", "other_non_working"}
VALID_LEAVE_TYPES = {"sick", "paid", "unpaid"}
REQUESTABLE_LEAVE_TYPES = {"sick", "paid"}
LEAVE_STATUSES = {"pending", "approved", "rejected", "cancelled"}


def get_calendar_date(calendar_date: date) -> Optional[Dict[str, Any]]:
    result = (get_service_client().table("company_calendar").select("*")
              .eq("calendar_date", calendar_date.isoformat()).maybe_single().execute())
    if result is None:
        return None
    return result.data


def _default_day_status(calendar_date: date) -> Dict[str, Any]:
    # Monday-Saturday are working by default; Sunday is non-working unless
    # an administrator explicitly overrides that date in company_calendar.
    if calendar_date.weekday() == 6:
        return {"calendar_date": calendar_date.isoformat(), "day_type": "sunday",
                "is_working_day": False, "name": "Sunday", "explicit": False}
    return {"calendar_date": calendar_date.isoformat(), "day_type": "working_day",
            "is_working_day": True, "name": None, "explicit": False}


def get_day_status(calendar_date: date) -> Dict[str, Any]:
    row = get_calendar_date(calendar_date)
    if not row:
        return _default_day_status(calendar_date)
    return {"calendar_date": calendar_date.isoformat(), "day_type": row["day_type"],
            "is_working_day": row["is_working_day"], "name": row.get("name"), "explicit": True,
            "created_by": row.get("created_by"), "created_at": row.get("created_at"),
            "updated_by": row.get("updated_by"), "updated_at": row.get("updated_at")}


def is_working_day(calendar_date: date) -> bool:
    return bool(get_day_status(calendar_date)["is_working_day"])


def get_month_calendar(year: int, month: int) -> List[Dict[str, Any]]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month.")
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    rows = (get_service_client().table("company_calendar").select("*")
            .gte("calendar_date", start.isoformat()).lt("calendar_date", end.isoformat())
            .order("calendar_date").execute().data or [])
    by_date = {r["calendar_date"]: r for r in rows}
    out = []
    for day in range(1, monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        out.append(get_day_status(d) if d.isoformat() in by_date else _default_day_status(d))
    return out


def _actor_role(employee_id: str) -> str:
    row = (get_service_client().table("employees").select("role,is_active")
           .eq("id", employee_id).maybe_single().execute())
    if row is None or not row.data or not row.data.get("is_active"):
        raise HTTPException(status_code=403, detail="Active employee account required.")
    return row.data["role"]


def _employee_row(employee_id: str) -> Dict[str, Any]:
    result = (get_service_client().table("employees")
              .select("id,name,employee_code,role,is_active,joining_date")
              .eq("id", employee_id).maybe_single().execute())
    if result is None or not result.data or not result.data.get("is_active"):
        raise HTTPException(status_code=404, detail="Employee not found or inactive.")
    return result.data


def set_calendar_date(calendar_date: date, day_type: str, is_working_day_value: bool,
                      name: Optional[str], performed_by: str) -> Dict[str, Any]:
    if day_type not in VALID_DAY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid calendar day type.")
    if day_type == "working_day":
        is_working_day_value = True
    elif day_type in {"holiday", "other_non_working"}:
        is_working_day_value = False
    client = get_service_client()
    existing = get_calendar_date(calendar_date)
    payload = {"calendar_date": calendar_date.isoformat(), "day_type": day_type,
               "is_working_day": bool(is_working_day_value), "name": name or None,
               "updated_by": performed_by}
    if existing:
        old = {k: existing.get(k) for k in ("calendar_date", "day_type", "is_working_day", "name")}
        row = client.table("company_calendar").update(payload).eq("calendar_date", calendar_date.isoformat()).execute().data[0]
        audit_service.write_audit_log(action="COMPANY_CALENDAR_UPDATED", old_value=old,
                                      new_value={k: row.get(k) for k in old}, performed_by=performed_by, reason=name)
        return row
    payload["created_by"] = performed_by
    row = client.table("company_calendar").insert(payload).execute().data[0]
    audit_service.write_audit_log(action="COMPANY_CALENDAR_CREATED",
                                  new_value={k: row.get(k) for k in ("calendar_date", "day_type", "is_working_day", "name")},
                                  performed_by=performed_by, reason=name)
    return row


def get_leave_for_employee_date(employee_id: str, leave_date: date) -> Optional[Dict[str, Any]]:
    result = (get_service_client().table("employee_leaves").select("*").eq("employee_id", employee_id)
              .eq("leave_date", leave_date.isoformat()).maybe_single().execute())
    if result is None:
        return None
    return result.data


def get_employee_leaves(employee_id: str, start_date: Optional[date] = None,
                        end_date: Optional[date] = None) -> List[Dict[str, Any]]:
    q = get_service_client().table("employee_leaves").select("*").eq("employee_id", employee_id)
    if start_date:
        q = q.gte("leave_date", start_date.isoformat())
    if end_date:
        q = q.lte("leave_date", end_date.isoformat())
    return q.order("leave_date", desc=True).execute().data or []


def get_all_leaves(start_date: Optional[date] = None, end_date: Optional[date] = None,
                   employee_id: Optional[str] = None, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    if status_filter and status_filter not in LEAVE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid leave status.")
    q = get_service_client().table("employee_leaves").select("*")
    if employee_id:
        q = q.eq("employee_id", employee_id)
    if start_date:
        q = q.gte("leave_date", start_date.isoformat())
    if end_date:
        q = q.lte("leave_date", end_date.isoformat())
    if status_filter:
        q = q.eq("status", status_filter)
    return q.order("leave_date", desc=True).execute().data or []


def get_leave_balance(employee_id: str) -> Dict[str, Any]:
    rows = get_employee_leaves(employee_id)
    approved = [r for r in rows if r.get("status") == "approved"]
    standard_paid = sum(r.get("leave_type") == "paid" and not r.get("is_additional") for r in approved)
    standard_sick = sum(r.get("leave_type") == "sick" and not r.get("is_additional") for r in approved)
    additional_paid = sum(r.get("leave_type") == "paid" and r.get("is_additional") for r in approved)
    additional_sick = sum(r.get("leave_type") == "sick" and r.get("is_additional") for r in approved)
    unpaid = sum(r.get("leave_type") == "unpaid" for r in approved)
    return {"standard": {"paid": {"used": standard_paid, "remaining": max(0, 1-standard_paid)},
                          "sick": {"used": standard_sick, "remaining": max(0, 1-standard_sick)}},
            "additional": {"paid": additional_paid, "sick": additional_sick}, "unpaid": unpaid}


def _ensure_leave_date_allowed(employee_id: str, leave_date: date) -> None:
    today = get_office_today(get_settings())
    if leave_date < today:
        raise HTTPException(status_code=400, detail="Leave can only be requested for today or a future working day.")
    if not is_working_day(leave_date):
        raise HTTPException(status_code=400, detail="Leave cannot be requested for a company non-working day.")
    target = _employee_row(employee_id)
    if target.get("joining_date") and leave_date < date.fromisoformat(target["joining_date"]):
        raise HTTPException(status_code=400, detail="Leave cannot be requested before the joining date.")


def request_leave(employee_id: str, leave_date: date, leave_type: str,
                  reason: Optional[str]) -> Dict[str, Any]:
    actor = _employee_row(employee_id)
    if actor["role"] not in {"employee", "admin"}:
        raise HTTPException(status_code=403, detail="Super Admin does not need to request leave for approval.")
    if leave_type not in REQUESTABLE_LEAVE_TYPES:
        raise HTTPException(status_code=400, detail="Employees can request only paid or sick leave.")
    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required for a leave request.")
    _ensure_leave_date_allowed(employee_id, leave_date)

    existing = get_leave_for_employee_date(employee_id, leave_date)
    if existing and existing.get("status") in {"pending", "approved"}:
        raise HTTPException(status_code=409, detail="A leave request already exists for this date.")

    balance = get_leave_balance(employee_id)
    remaining = balance["standard"][leave_type]["remaining"]
    if remaining <= 0:
        raise HTTPException(status_code=409, detail=f"Your standard {leave_type} leave has already been used.")

    client = get_service_client()
    payload = {"employee_id": employee_id, "leave_date": leave_date.isoformat(), "leave_type": leave_type,
               "status": "pending", "is_additional": False, "reason": reason.strip(), "granted_by": None}
    if existing:
        row = client.table("employee_leaves").update(payload).eq("id", existing["id"]).execute().data[0]
    else:
        row = client.table("employee_leaves").insert(payload).execute().data[0]
    audit_service.write_audit_log(action="LEAVE_REQUESTED", employee_id=employee_id,
                                  new_value={k: row.get(k) for k in ("leave_date","leave_type","status","reason")},
                                  performed_by=employee_id, reason=reason.strip())
    return row


def _validate_approval_actor(actor_id: str, target_employee_id: str) -> str:
    actor_role = _actor_role(actor_id)
    if actor_role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Only Admin or Super Admin can approve leave requests.")
    target = _employee_row(target_employee_id)
    if target["role"] == "super_admin":
        raise HTTPException(status_code=403, detail="Super Admin profiles cannot have leave requests.")
    if target["role"] == "admin" and actor_role != "super_admin":
        raise HTTPException(status_code=403, detail="Only Super Admin can approve or reject an Admin's leave request.")
    return actor_role


def approve_leave_request(leave_id: str, approved_by: str) -> Dict[str, Any]:
    client = get_service_client()
    result = client.table("employee_leaves").select("*").eq("id", leave_id).maybe_single().execute()
    if result is None or not result.data:
        raise HTTPException(status_code=404, detail="Leave request not found.")
    existing = result.data
    if existing.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Only pending leave requests can be approved.")
    _validate_approval_actor(approved_by, existing["employee_id"])
    _ensure_leave_date_allowed(existing["employee_id"], date.fromisoformat(existing["leave_date"]))
    balance = get_leave_balance(existing["employee_id"])
    leave_type = existing["leave_type"]
    if leave_type not in REQUESTABLE_LEAVE_TYPES or balance["standard"][leave_type]["remaining"] <= 0:
        raise HTTPException(status_code=409, detail=f"No remaining standard {leave_type} leave is available for this employee.")
    row = client.table("employee_leaves").update({"status": "approved", "granted_by": approved_by}).eq("id", leave_id).execute().data[0]
    audit_service.write_audit_log(action="LEAVE_APPROVED", employee_id=existing["employee_id"],
                                  old_value={"status": "pending"},
                                  new_value={k: row.get(k) for k in ("leave_date","leave_type","status","granted_by")},
                                  performed_by=approved_by)
    return row


def reject_leave_request(leave_id: str, rejected_by: str, reason: Optional[str]) -> Dict[str, Any]:
    client = get_service_client()
    result = client.table("employee_leaves").select("*").eq("id", leave_id).maybe_single().execute()
    if result is None or not result.data:
        raise HTTPException(status_code=404, detail="Leave request not found.")
    existing = result.data
    if existing.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Only pending leave requests can be rejected.")
    _validate_approval_actor(rejected_by, existing["employee_id"])
    row = client.table("employee_leaves").update({"status": "rejected", "granted_by": rejected_by}).eq("id", leave_id).execute().data[0]
    audit_service.write_audit_log(action="LEAVE_REJECTED", employee_id=existing["employee_id"],
                                  old_value={"status": "pending"},
                                  new_value={"status": "rejected"}, performed_by=rejected_by, reason=reason)
    return row


def grant_leave(employee_id: str, leave_date: date, leave_type: str, is_additional: bool,
                reason: Optional[str], granted_by: str) -> Dict[str, Any]:
    if leave_type not in VALID_LEAVE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid leave type.")
    actor_role = _actor_role(granted_by)
    _employee_row(employee_id)
    existing = get_leave_for_employee_date(employee_id, leave_date)
    if existing and existing.get("status") == "approved":
        raise HTTPException(status_code=409, detail="Leave already exists for this date.")
    if actor_role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Only Admin or Super Admin can grant leave.")
    if actor_role == "admin" and is_additional and leave_type in {"paid", "sick"}:
        raise HTTPException(status_code=403, detail="Only Super Admin can grant additional paid or sick leave.")
    balance = get_leave_balance(employee_id)
    if actor_role == "admin":
        if leave_type == "paid" and not is_additional and balance["standard"]["paid"]["remaining"] <= 0:
            raise HTTPException(status_code=409, detail="Standard paid leave has already been used.")
        if leave_type == "sick" and not is_additional and balance["standard"]["sick"]["remaining"] <= 0:
            raise HTTPException(status_code=409, detail="Standard sick leave has already been used.")
        if leave_type == "unpaid" and (balance["standard"]["paid"]["used"] < 1 or balance["standard"]["sick"]["used"] < 1):
            raise HTTPException(status_code=409, detail="Unpaid leave can be granted by Admin only after the standard paid and sick leaves are used.")
        is_additional = False
    client = get_service_client()
    payload = {"employee_id": employee_id, "leave_date": leave_date.isoformat(), "leave_type": leave_type,
               "status": "approved", "is_additional": bool(is_additional), "reason": reason, "granted_by": granted_by}
    if existing and existing.get("status") in {"cancelled", "rejected"}:
        row = client.table("employee_leaves").update(payload).eq("id", existing["id"]).execute().data[0]
    elif existing:
        raise HTTPException(status_code=409, detail="A leave request already exists for this date.")
    else:
        row = client.table("employee_leaves").insert(payload).execute().data[0]
    audit_service.write_audit_log(action="LEAVE_CREATED", employee_id=employee_id,
                                  new_value={k: row.get(k) for k in ("leave_date","leave_type","status","is_additional","reason")},
                                  performed_by=granted_by, reason=reason)
    return row


def cancel_leave(leave_id: str, performed_by: str, reason: Optional[str]) -> Dict[str, Any]:
    role = _actor_role(performed_by)
    if role not in {"admin", "super_admin"}:
        raise HTTPException(status_code=403, detail="Only Admin or Super Admin can cancel leave.")
    client = get_service_client()
    result = client.table("employee_leaves").select("*").eq("id", leave_id).maybe_single().execute()
    if result is None or not result.data:
        raise HTTPException(status_code=404, detail="Leave record not found.")
    existing = result.data
    if existing.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Leave is already cancelled.")
    row = client.table("employee_leaves").update({"status": "cancelled"}).eq("id", leave_id).execute().data[0]
    audit_service.write_audit_log(action="LEAVE_CANCELLED", employee_id=existing["employee_id"],
                                  old_value={k: existing.get(k) for k in ("leave_date","leave_type","status","is_additional")},
                                  new_value={k: row.get(k) for k in ("leave_date","leave_type","status","is_additional")},
                                  performed_by=performed_by, reason=reason)
    return row
