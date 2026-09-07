"""
Company calendar and leave business logic.

The company calendar is the single source of truth for whether a date
is a working day.

Important:
- Sundays are NOT automatically non-working.
- Holidays are NOT inferred automatically.
- Admin/Super Admin explicitly designate dates.
- Dates without a calendar row are normal working days.
- Employees can read the calendar but cannot modify it.
- Calendar/leave writes are authorized by the router and additionally
  validated here where business rules matter.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.services import audit_service
from app.services.supabase_client import get_service_client


VALID_DAY_TYPES = {
    "working_day",
    "sunday",
    "holiday",
    "other_non_working",
}

VALID_LEAVE_TYPES = {
    "sick",
    "paid",
    "unpaid",
}

VALID_LEAVE_STATUSES = {
    "approved",
    "cancelled",
}


# -----------------------------------------------------------------------
# Calendar
# -----------------------------------------------------------------------

def get_calendar_date(calendar_date: date) -> Optional[Dict[str, Any]]:
    client = get_service_client()

    result = (
        client.table("company_calendar")
        .select("*")
        .eq("calendar_date", calendar_date.isoformat())
        .maybe_single()
        .execute()
    )

    if result is None:
        return None

    return result.data


def get_day_status(calendar_date: date) -> Dict[str, Any]:
    """
    Return the company's working-day decision for one date.

    If no explicit calendar row exists, the date is considered a normal
    working day. This deliberately avoids hard-coding Sunday behavior.
    """

    row = get_calendar_date(calendar_date)

    if not row:
        return {
            "calendar_date": calendar_date.isoformat(),
            "day_type": "working_day",
            "is_working_day": True,
            "name": None,
            "explicit": False,
        }

    return {
        "calendar_date": calendar_date.isoformat(),
        "day_type": row["day_type"],
        "is_working_day": row["is_working_day"],
        "name": row.get("name"),
        "explicit": True,
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
        "updated_by": row.get("updated_by"),
        "updated_at": row.get("updated_at"),
    }


def is_working_day(calendar_date: date) -> bool:
    return bool(get_day_status(calendar_date)["is_working_day"])


def get_month_calendar(year: int, month: int) -> List[Dict[str, Any]]:
    """
    Return every explicit company-calendar entry for a month.

    The frontend can combine these with normal working days for dates
    that have no explicit row.
    """

    if month < 1 or month > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid month.",
        )

    start_date = date(year, month, 1)

    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    client = get_service_client()

    result = (
        client.table("company_calendar")
        .select("*")
        .gte("calendar_date", start_date.isoformat())
        .lt("calendar_date", end_date.isoformat())
        .order("calendar_date")
        .execute()
    )

    return result.data or []


def set_calendar_date(
    calendar_date: date,
    day_type: str,
    is_working_day_value: bool,
    name: Optional[str],
    performed_by: str,
) -> Dict[str, Any]:
    """
    Create or update one company calendar date.

    Admin and Super Admin authorization is handled by the router.
    """

    if day_type not in VALID_DAY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid calendar day type.",
        )

    if not name:
        name = None

    client = get_service_client()
    existing = get_calendar_date(calendar_date)

    payload = {
        "calendar_date": calendar_date.isoformat(),
        "day_type": day_type,
        "is_working_day": is_working_day_value,
        "name": name,
        "updated_by": performed_by,
    }

    if existing:
        old_value = {
            "calendar_date": existing.get("calendar_date"),
            "day_type": existing.get("day_type"),
            "is_working_day": existing.get("is_working_day"),
            "name": existing.get("name"),
        }

        result = (
            client.table("company_calendar")
            .update(payload)
            .eq("calendar_date", calendar_date.isoformat())
            .execute()
        )

        row = result.data[0]

        audit_service.write_audit_log(
            action="COMPANY_CALENDAR_UPDATED",
            old_value=old_value,
            new_value={
                "calendar_date": row.get("calendar_date"),
                "day_type": row.get("day_type"),
                "is_working_day": row.get("is_working_day"),
                "name": row.get("name"),
            },
            performed_by=performed_by,
            reason=name,
        )

        return row

    payload["created_by"] = performed_by

    result = (
        client.table("company_calendar")
        .insert(payload)
        .execute()
    )

    row = result.data[0]

    audit_service.write_audit_log(
        action="COMPANY_CALENDAR_CREATED",
        new_value={
            "calendar_date": row.get("calendar_date"),
            "day_type": row.get("day_type"),
            "is_working_day": row.get("is_working_day"),
            "name": row.get("name"),
        },
        performed_by=performed_by,
        reason=name,
    )

    return row


# -----------------------------------------------------------------------
# Leave
# -----------------------------------------------------------------------

def get_leave_for_employee_date(
    employee_id: str,
    leave_date: date,
) -> Optional[Dict[str, Any]]:
    client = get_service_client()

    result = (
        client.table("employee_leaves")
        .select("*")
        .eq("employee_id", employee_id)
        .eq("leave_date", leave_date.isoformat())
        .maybe_single()
        .execute()
    )

    if result is None:
        return None

    return result.data


def get_employee_leaves(
    employee_id: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict[str, Any]]:
    client = get_service_client()

    query = (
        client.table("employee_leaves")
        .select("*")
        .eq("employee_id", employee_id)
    )

    if start_date:
        query = query.gte("leave_date", start_date.isoformat())

    if end_date:
        query = query.lte("leave_date", end_date.isoformat())

    result = (
        query
        .order("leave_date", desc=True)
        .execute()
    )

    return result.data or []


def get_all_leaves(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    employee_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = get_service_client()

    query = client.table("employee_leaves").select("*")

    if employee_id:
        query = query.eq("employee_id", employee_id)

    if start_date:
        query = query.gte("leave_date", start_date.isoformat())

    if end_date:
        query = query.lte("leave_date", end_date.isoformat())

    result = (
        query
        .order("leave_date", desc=True)
        .execute()
    )

    return result.data or []


def grant_leave(
    employee_id: str,
    leave_date: date,
    leave_type: str,
    is_additional: bool,
    reason: Optional[str],
    granted_by: str,
) -> Dict[str, Any]:
    """
    Grant one full-day leave.

    Business rules:
    - paid/sick normal leave consumes the employee's standard allocation.
    - additional paid/sick leave is intended for Super Admin grants.
    - unpaid leave does not consume paid/sick allocation.
    """

    if leave_type not in VALID_LEAVE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid leave type.",
        )

    existing = get_leave_for_employee_date(employee_id, leave_date)

    if existing and existing.get("status") == "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Leave already exists for this date.",
        )

    client = get_service_client()

    payload = {
        "employee_id": employee_id,
        "leave_date": leave_date.isoformat(),
        "leave_type": leave_type,
        "status": "approved",
        "is_additional": bool(is_additional),
        "reason": reason,
        "granted_by": granted_by,
    }

    if existing and existing.get("status") == "cancelled":
        result = (
            client.table("employee_leaves")
            .update(payload)
            .eq("id", existing["id"])
            .execute()
        )
    else:
        result = (
            client.table("employee_leaves")
            .insert(payload)
            .execute()
        )

    row = result.data[0]

    audit_service.write_audit_log(
        action="LEAVE_CREATED",
        employee_id=employee_id,
        new_value={
            "leave_date": row.get("leave_date"),
            "leave_type": row.get("leave_type"),
            "status": row.get("status"),
            "is_additional": row.get("is_additional"),
            "reason": row.get("reason"),
        },
        performed_by=granted_by,
        reason=reason,
    )

    return row


def cancel_leave(
    leave_id: str,
    performed_by: str,
    reason: Optional[str],
) -> Dict[str, Any]:
    client = get_service_client()

    existing_result = (
        client.table("employee_leaves")
        .select("*")
        .eq("id", leave_id)
        .maybe_single()
        .execute()
    )

    if existing_result is None or not existing_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Leave record not found.",
        )

    existing = existing_result.data

    if existing.get("status") == "cancelled":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Leave is already cancelled.",
        )

    result = (
        client.table("employee_leaves")
        .update({
            "status": "cancelled",
        })
        .eq("id", leave_id)
        .execute()
    )

    row = result.data[0]

    audit_service.write_audit_log(
        action="LEAVE_CANCELLED",
        employee_id=existing["employee_id"],
        old_value={
            "leave_date": existing.get("leave_date"),
            "leave_type": existing.get("leave_type"),
            "status": existing.get("status"),
            "is_additional": existing.get("is_additional"),
        },
        new_value={
            "leave_date": row.get("leave_date"),
            "leave_type": row.get("leave_type"),
            "status": row.get("status"),
            "is_additional": row.get("is_additional"),
        },
        performed_by=performed_by,
        reason=reason,
    )

    return row
