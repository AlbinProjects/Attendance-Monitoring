"""
Admin dashboard aggregation service.

Every query here is enriched with employee name/department in Python
rather than a database-side join, trading a few extra round trips for
simplicity and testability — reasonable at the scale of an internal
company tool. All filtering (department, status, inactivity flag) happens
server-side; the admin UI never has to fetch everything and filter
client-side.
"""

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from app.config import Settings
from app.services import activity_service, break_service
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_today


def _get_all_employees() -> List[Dict[str, Any]]:
    client = get_service_client()
    result = client.table("employees").select("*").execute()
    return result.data or []


def _get_active_employees() -> List[Dict[str, Any]]:
    # Dashboard employee metrics are for actual employees only. Admin and
    # super_admin accounts may have attendance records, but they must never
    # inflate employee totals, absence counts, performance-missing counts,
    # or employee activity flags.
    return [
        e
        for e in _get_all_employees()
        if e.get("is_active") and e.get("role") == "employee"
    ]


# -----------------------------------------------------------------------
# Overview dashboard
# -----------------------------------------------------------------------

def get_dashboard_stats(settings: Settings) -> Dict[str, Any]:
    today = get_office_today(settings)
    yesterday = today - timedelta(days=1)

    active_employees = _get_active_employees()
    active_ids = {e["id"] for e in active_employees}
    total_employees = len(active_employees)

    client = get_service_client()
    today_attendance = (
        client.table("attendance").select("*").eq("attendance_date", today.isoformat()).execute().data or []
    )
    today_attendance = [r for r in today_attendance if r["employee_id"] in active_ids]

    present_today = sum(1 for r in today_attendance if r["status"] == "present")
    late_today = sum(1 for r in today_attendance if r["status"] == "late")
    half_day_today = sum(1 for r in today_attendance if r["status"] == "half_day")
    manual_today = sum(1 for r in today_attendance if r["status"] == "manual")
    checked_in_ids = {r["employee_id"] for r in today_attendance}

    # "Absent" here means "no attendance record yet today" for an active
    # employee — this is NOT a confirmed absence. There is no automatic
    # end-of-day absence-marking job in this system (status='absent' is
    # only ever set explicitly by an admin via manual attendance, Phase 9).
    # An employee who simply hasn't checked in YET today will show here
    # until they do, or until an admin marks them.
    absent_today = total_employees - len(checked_in_ids)

    yesterday_rows = (
        client.table("performance_updates")
        .select("employee_id, submitted_at")
        .eq("work_date", yesterday.isoformat())
        .execute()
        .data
        or []
    )
    submitted_yesterday_ids = {r["employee_id"] for r in yesterday_rows if r.get("submitted_at")}
    eligible_for_yesterday = [
        e
        for e in active_employees
        if not e.get("joining_date") or e["joining_date"] <= yesterday.isoformat()
    ]
    missing_performance_count = sum(
        1 for e in eligible_for_yesterday if e["id"] not in submitted_yesterday_ids
    )

    inactivity_flags_count = 0
    for row in today_attendance:
        summary = activity_service.get_activity_summary_for_attendance(row, settings)
        if summary["flagged"]:
            inactivity_flags_count += 1

    return {
        "total_employees": total_employees,
        "present_today": present_today,
        "late_today": late_today,
        "half_day_today": half_day_today,
        "manual_today": manual_today,
        "absent_today": absent_today,
        "missing_performance_count": missing_performance_count,
        "inactivity_flags_count": inactivity_flags_count,
    }


def get_dashboard_details(settings: Settings, metric: str) -> Dict[str, Any]:
    """Return the employees represented by one dashboard statistic.

    The dashboard count and this drill-down intentionally use the same
    business rules: active employees for attendance widgets, yesterday for
    missing performance, and today's attendance/activity for activity flags.
    """
    allowed = {
        "present", "late", "not_checked_in", "half_day",
        "manual", "missing_performance", "inactivity",
    }
    if metric not in allowed:
        raise ValueError("Unknown dashboard metric")

    today = get_office_today(settings)
    yesterday = today - timedelta(days=1)
    active_employees = _get_active_employees()
    active_by_id = {e["id"]: e for e in active_employees}
    client = get_service_client()

    today_rows = (
        client.table("attendance")
        .select("*")
        .eq("attendance_date", today.isoformat())
        .execute()
        .data
        or []
    )
    today_rows = [r for r in today_rows if r.get("employee_id") in active_by_id]

    if metric == "not_checked_in":
        checked_ids = {r["employee_id"] for r in today_rows}
        rows = []
        for employee in active_employees:
            if employee["id"] not in checked_ids:
                rows.append({
                    "id": employee["id"],
                    "employee_name": employee.get("name"),
                    "employee_code": employee.get("employee_code"),
                    "department": employee.get("department"),
                })
        return {"metric": metric, "date": today.isoformat(), "rows": rows}

    if metric == "missing_performance":
        performance_rows = (
            client.table("performance_updates")
            .select("employee_id, submitted_at")
            .eq("work_date", yesterday.isoformat())
            .execute()
            .data
            or []
        )
        submitted_ids = {r["employee_id"] for r in performance_rows if r.get("submitted_at")}
        rows = []
        for employee in active_employees:
            joining_date = employee.get("joining_date")
            if joining_date and joining_date > yesterday.isoformat():
                continue
            if employee["id"] not in submitted_ids:
                rows.append({
                    "id": employee["id"],
                    "employee_name": employee.get("name"),
                    "employee_code": employee.get("employee_code"),
                    "department": employee.get("department"),
                })
        return {"metric": metric, "date": yesterday.isoformat(), "rows": rows}

    if metric == "inactivity":
        rows = []
        for attendance in today_rows:
            summary = activity_service.get_activity_summary_for_attendance(attendance, settings)
            if not summary["flagged"]:
                continue
            employee = active_by_id[attendance["employee_id"]]
            rows.append({
                "id": attendance["id"],
                "employee_name": employee.get("name"),
                "employee_code": employee.get("employee_code"),
                "department": employee.get("department"),
                "status": attendance.get("status"),
                "check_in": attendance.get("check_in"),
                "counted_inactivity_seconds": summary["counted_inactivity_seconds"],
            })
        return {"metric": metric, "date": today.isoformat(), "rows": rows}

    rows = []
    for attendance in today_rows:
        if attendance.get("status") != metric:
            continue
        employee = active_by_id[attendance["employee_id"]]
        rows.append({
            "id": attendance["id"],
            "employee_name": employee.get("name"),
            "employee_code": employee.get("employee_code"),
            "department": employee.get("department"),
            "status": attendance.get("status"),
            "check_in": attendance.get("check_in"),
        })

    rows.sort(key=lambda r: (r.get("employee_name") or "").lower())
    return {"metric": metric, "date": today.isoformat(), "rows": rows}


# -----------------------------------------------------------------------
# Attendance table
# -----------------------------------------------------------------------

def get_admin_attendance(
    settings: Settings,
    *,
    on_date: Optional[date] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    inactivity_flag: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    client = get_service_client()
    query = client.table("attendance").select("*")
    if on_date:
        query = query.eq("attendance_date", on_date.isoformat())
    if employee_id:
        query = query.eq("employee_id", employee_id)
    if status:
        query = query.eq("status", status)
    if source:
        query = query.eq("check_in_source", source)
    rows = query.execute().data or []

    # Include inactive employees too — historical attendance rows must
    # still display correctly for someone who has since been disabled.
    employees = {e["id"]: e for e in _get_all_employees()}

    enriched = []
    for row in rows:
        emp = employees.get(row["employee_id"], {})
        if department and emp.get("department") != department:
            continue

        summary = activity_service.get_activity_summary_for_attendance(row, settings)
        break_summary = break_service.get_break_summary(row["id"])
        if inactivity_flag is not None and summary["flagged"] != inactivity_flag:
            continue

        # A check-in without a check-out is only an open session on the same
        # calendar day. From the following day onward it is a missed check-out
        # and must be visible to Admin/Super Admin without changing the stored
        # attendance status.
        attendance_date = date.fromisoformat(row["attendance_date"])
        checkout_missed = bool(
            row.get("check_in")
            and not row.get("check_out")
            and attendance_date < get_office_today(settings)
        )

        enriched.append(
            {
                **row,
                "employee_name": emp.get("name"),
                "employee_code": emp.get("employee_code"),
                "department": emp.get("department"),
                "total_session_seconds": summary["total_session_seconds"],
                "counted_inactivity_seconds": summary["counted_inactivity_seconds"],
                "active_session_seconds": summary["active_session_seconds"],
                "total_break_seconds": break_summary["total_break_seconds"],
                "breaks": break_summary["sessions"],
                "inactivity_flag": summary["flagged"],
                "checkout_missed": checkout_missed,
            }
        )

    enriched.sort(key=lambda r: (r["attendance_date"], r.get("employee_name") or ""), reverse=True)
    return enriched


# -----------------------------------------------------------------------
# Performance table
# -----------------------------------------------------------------------

def get_admin_performance(
    settings: Settings,
    *,
    on_date: Optional[date] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    client = get_service_client()
    query = client.table("performance_updates").select("*")
    if on_date:
        query = query.eq("work_date", on_date.isoformat())
    if employee_id:
        query = query.eq("employee_id", employee_id)
    if status:
        query = query.eq("status", status)
    rows = query.execute().data or []

    employees = {e["id"]: e for e in _get_all_employees()}

    enriched = []
    for row in rows:
        emp = employees.get(row["employee_id"], {})
        if department and emp.get("department") != department:
            continue
        enriched.append(
            {
                **row,
                "employee_name": emp.get("name"),
                "employee_code": emp.get("employee_code"),
                "department": emp.get("department"),
            }
        )

    enriched.sort(key=lambda r: (r["work_date"], r.get("employee_name") or ""), reverse=True)
    return enriched


# -----------------------------------------------------------------------
# Activity table
# -----------------------------------------------------------------------

def get_admin_activity(
    settings: Settings,
    *,
    on_date: Optional[date] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    flag: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    attendance_rows = get_admin_attendance(
        settings,
        on_date=on_date,
        employee_id=employee_id,
        department=department,
        inactivity_flag=flag,
    )
    return [
        {
            "attendance_id": r["id"],
            "employee_id": r["employee_id"],
            "employee_name": r["employee_name"],
            "department": r["department"],
            "attendance_date": r["attendance_date"],
            "check_in": r["check_in"],
            "check_out": r["check_out"],
            "total_session_seconds": r["total_session_seconds"],
            "counted_inactivity_seconds": r["counted_inactivity_seconds"],
            "active_session_seconds": r["active_session_seconds"],
            "flagged": r["inactivity_flag"],
        }
        for r in attendance_rows
    ]
