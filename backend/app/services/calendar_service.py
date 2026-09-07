"""Company calendar and leave business logic."""
from calendar import monthrange
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.services import audit_service
from app.services.supabase_client import get_service_client

VALID_DAY_TYPES = {"working_day", "sunday", "holiday", "other_non_working"}
VALID_LEAVE_TYPES = {"sick", "paid", "unpaid"}


def get_calendar_date(calendar_date: date) -> Optional[Dict[str, Any]]:
    result = (get_service_client().table("company_calendar").select("*")
              .eq("calendar_date", calendar_date.isoformat()).maybe_single().execute())
    if result is None:
        return None
    return result.data


def get_day_status(calendar_date: date) -> Dict[str, Any]:
    """Return the company working-day status for one date.

    Defaults: Monday-Saturday are working days; Sunday is non-working.
    Admin/Super Admin can explicitly override a Sunday to working by saving
    that date with day_type='sunday' and is_working_day=True. Holidays and
    other non-working dates are also explicitly stored in the calendar.
    """
    row = get_calendar_date(calendar_date)
    if not row:
        is_sunday = calendar_date.weekday() == 6
        return {
            "calendar_date": calendar_date.isoformat(),
            "day_type": "sunday" if is_sunday else "working_day",
            "is_working_day": not is_sunday,
            "name": None,
            "explicit": False,
        }
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
        row = by_date.get(d.isoformat())
        out.append(get_day_status(d))
    return out


def _actor_role(employee_id: str) -> str:
    row = (get_service_client().table("employees").select("role,is_active")
           .eq("id", employee_id).maybe_single().execute())
    if row is None or not row.data or not row.data.get("is_active"):
        raise HTTPException(status_code=403, detail="Active employee account required.")
    return row.data["role"]


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
    if start_date: q = q.gte("leave_date", start_date.isoformat())
    if end_date: q = q.lte("leave_date", end_date.isoformat())
    return q.order("leave_date", desc=True).execute().data or []


def get_all_leaves(start_date: Optional[date] = None, end_date: Optional[date] = None,
                   employee_id: Optional[str] = None) -> List[Dict[str, Any]]:
    q = get_service_client().table("employee_leaves").select("*")
    if employee_id: q = q.eq("employee_id", employee_id)
    if start_date: q = q.gte("leave_date", start_date.isoformat())
    if end_date: q = q.lte("leave_date", end_date.isoformat())
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


def grant_leave(employee_id: str, leave_date: date, leave_type: str, is_additional: bool,
                reason: Optional[str], granted_by: str) -> Dict[str, Any]:
    if leave_type not in VALID_LEAVE_TYPES:
        raise HTTPException(status_code=400, detail="Invalid leave type.")
    actor_role = _actor_role(granted_by)
    target = (get_service_client().table("employees").select("id,is_active").eq("id", employee_id).maybe_single().execute())
    if target is None or not target.data or not target.data.get("is_active"):
        raise HTTPException(status_code=404, detail="Employee not found or inactive.")
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
    if existing and existing.get("status") == "cancelled":
        row = client.table("employee_leaves").update(payload).eq("id", existing["id"]).execute().data[0]
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
