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
VALID_LEAVE_TYPES = {"sick", "paid", "unpaid", "half_day"}
REQUESTABLE_LEAVE_TYPES = {"sick", "paid", "half_day"}
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
                  reason: Optional[str], half_day_period: Optional[str] = None) -> Dict[str, Any]:
    actor = _employee_row(employee_id)
    if actor["role"] not in {"employee", "admin"}:
        raise HTTPException(status_code=403, detail="Super Admin does not need to request leave for approval.")
    if leave_type not in REQUESTABLE_LEAVE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid leave type.")
    if leave_type == "half_day" and half_day_period not in {"morning", "afternoon"}:
        raise HTTPException(status_code=400, detail="Choose whether the half-day leave is for the morning or afternoon.")
    if leave_type != "half_day" and half_day_period is not None:
        raise HTTPException(status_code=400, detail="Half-day period is only valid for half-day leave.")
    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="A reason is required for a leave request.")
    _ensure_leave_date_allowed(employee_id, leave_date)

    existing = get_leave_for_employee_date(employee_id, leave_date)
    if existing and existing.get("status") in {"pending", "approved"}:
        raise HTTPException(status_code=409, detail="A leave request already exists for this date.")

    # Half-day leave is independently approvable and does not consume the
    # standard paid/sick balances. It can be requested in advance (today or
    # any future working day), as well as after four hours through the
    # checkout workflow.
    if leave_type != "half_day":
        balance = get_leave_balance(employee_id)
        remaining = balance["standard"][leave_type]["remaining"]
        if remaining <= 0:
            raise HTTPException(status_code=409, detail=f"Your standard {leave_type} leave has already been used.")

    client = get_service_client()
    payload = {"employee_id": employee_id, "leave_date": leave_date.isoformat(), "leave_type": leave_type,
               "half_day_period": half_day_period if leave_type == "half_day" else None,
               "status": "pending", "is_additional": False, "reason": reason.strip(), "granted_by": None}
    if existing:
        row = client.table("employee_leaves").update(payload).eq("id", existing["id"]).execute().data[0]
    else:
        row = client.table("employee_leaves").insert(payload).execute().data[0]
    audit_service.write_audit_log(action="LEAVE_REQUESTED", employee_id=employee_id,
                                  new_value={k: row.get(k) for k in ("leave_date","leave_type","half_day_period","status","reason")},
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


def request_half_day_leave(employee_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Checkout-specific half-day request.

    The Calendar leave request can request a half-day in advance. This
    endpoint remains stricter because it is exposed by the checkout flow: the
    employee must have completed at least four net hours before using the
    shortcut to request half-day leave while checking out.
    """
    from datetime import datetime
    from app.services import break_service, remote_work_service, on_duty_service, attendance_service

    settings = get_settings()
    today = get_office_today(settings)
    if not is_working_day(today):
        raise HTTPException(status_code=400, detail="Half-day leave cannot be requested on a company non-working day.")

    attendance = attendance_service.get_attendance_for_date(employee_id, today)
    if not attendance or not attendance.get("check_in"):
        raise HTTPException(status_code=400, detail="You must check in before using the checkout half-day option. For an earlier request, use Calendar → Request leave → Half-day leave.")

    end_dt = datetime.fromisoformat(attendance["check_out"]) if attendance.get("check_out") else get_office_now(settings)
    check_in_dt = datetime.fromisoformat(attendance["check_in"])
    summary = break_service.get_break_summary(attendance["id"], end_dt)
    gross = max(0, int((end_dt - check_in_dt).total_seconds()))
    net_seconds = max(0, gross - summary["total_break_seconds"])
    if net_seconds < 4 * 60 * 60:
        raise HTTPException(status_code=400, detail="You can use the checkout half-day option only after completing at least 4 net work hours.")
    if net_seconds >= 8 * 60 * 60:
        raise HTTPException(status_code=400, detail="You have already completed the 8-hour work target; half-day leave is not applicable.")

    remote = remote_work_service.get_today(employee_id)
    on_duty = on_duty_service.get_today(employee_id)
    if remote and remote.get("work_mode") == "other_site":
        raise HTTPException(status_code=400, detail="Half-day leave is not available for an Other Site work assignment.")
    if on_duty and on_duty.get("status") in {"approved", "started", "completed"}:
        raise HTTPException(status_code=400, detail="Half-day leave is not available for an On Duty session.")

    return request_leave(employee_id, today, "half_day", reason or "Half-day leave requested after completing 4 net work hours.", "afternoon")


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
    if leave_type == "half_day":
        # Half-day leave has its own approval state and does not consume the
        # standard paid/sick leave balances. It is only created by the
        # four-hour eligibility endpoint above.
        row = client.table("employee_leaves").update({"status": "approved", "granted_by": approved_by}).eq("id", leave_id).execute().data[0]
        attendance = (client.table("attendance").select("id,status,check_in,check_out")
                      .eq("employee_id", existing["employee_id"]).eq("attendance_date", existing["leave_date"]).maybe_single().execute())
        if attendance and attendance.data:
            client.table("attendance").update({"status": "half_day"}).eq("id", attendance.data["id"]).execute()
        audit_service.write_audit_log(action="LEAVE_APPROVED", employee_id=existing["employee_id"],
                                      attendance_id=attendance.data["id"] if attendance and attendance.data else None,
                                      old_value={"status": "pending"},
                                      new_value={"leave_date": row.get("leave_date"), "leave_type": row.get("leave_type"), "status": row.get("status"), "granted_by": row.get("granted_by")},
                                      performed_by=approved_by)
        return row
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
    auto_unpaid = bool(existing and existing.get("status") == "approved" and existing.get("leave_type") == "unpaid" and
                       str(existing.get("reason") or "").startswith("Auto-marked unpaid leave:"))
    if existing and existing.get("status") == "approved" and not auto_unpaid:
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
    if existing and (existing.get("status") in {"cancelled", "rejected"} or auto_unpaid):
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
