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
    # Employee-only population used by performance/activity metrics.
    return [
        e
        for e in _get_all_employees()
        if e.get("is_active") and e.get("role") == "employee"
    ]


def _get_active_attendance_staff() -> List[Dict[str, Any]]:
    # Attendance dashboard population includes real Employees and Admins.
    # Super Admin accounts are intentionally excluded because they do not
    # participate in check-in, check-out, breaks, or work-hour tracking.
    return [
        e
        for e in _get_all_employees()
        if e.get("is_active") and e.get("role") in {"employee", "admin"}
    ]


# -----------------------------------------------------------------------
# Overview dashboard
# -----------------------------------------------------------------------

def get_dashboard_stats(settings: Settings) -> Dict[str, Any]:
    today = get_office_today(settings)
    yesterday = today - timedelta(days=1)

    # Attendance metrics include active Employees + Admins. Super Admins are
    # deliberately excluded because they have no attendance/check-in/out
    # obligations. Performance and laptop-activity metrics remain employee-only.
    attendance_staff = _get_active_attendance_staff()
    active_employees = _get_active_employees()
    staff_ids = {e["id"] for e in attendance_staff}
    total_staff = len(attendance_staff)

    client = get_service_client()
    today_attendance = (
        client.table("attendance").select("*").eq("attendance_date", today.isoformat()).execute().data or []
    )
    today_attendance = [r for r in today_attendance if r.get("employee_id") in staff_ids]

    present_today = sum(1 for r in today_attendance if r.get("status") == "present")
    late_today = sum(1 for r in today_attendance if r.get("status") == "late")
    half_day_today = sum(1 for r in today_attendance if r.get("status") == "half_day")
    manual_today = sum(1 for r in today_attendance if r.get("status") == "manual")
    checked_in_ids = {r["employee_id"] for r in today_attendance}

    # Approved full-day leave, Other Site and On Duty do not require a normal
    # attendance punch, so they must not appear as "Not yet checked in".
    approved_leave_rows = (
        client.table("employee_leaves")
        .select("employee_id,leave_type")
        .eq("leave_date", today.isoformat())
        .eq("status", "approved")
        .execute().data or []
    )
    exempt_leave_ids = {
        r["employee_id"] for r in approved_leave_rows
        if r.get("leave_type") != "half_day" and r.get("employee_id") in staff_ids
    }

    remote_rows = (
        client.table("remote_work_requests")
        .select("employee_id,work_mode")
        .eq("work_date", today.isoformat())
        .in_("status", ["approved", "assigned", "started"])
        .execute().data or []
    )
    other_site_ids = {r["employee_id"] for r in remote_rows if r.get("work_mode") == "other_site" and r.get("employee_id") in staff_ids}

    on_duty_rows = (
        client.table("on_duty_requests")
        .select("employee_id")
        .eq("on_duty_date", today.isoformat())
        .in_("status", ["approved", "started", "completed"])
        .execute().data or []
    )
    on_duty_ids = {r["employee_id"] for r in on_duty_rows if r.get("employee_id") in staff_ids}

    exempt_ids = exempt_leave_ids | other_site_ids | on_duty_ids
    absent_today = sum(
        1 for staff in attendance_staff
        if staff["id"] not in checked_in_ids and staff["id"] not in exempt_ids
    )

    # Missing performance is intentionally employee-only. Admins do not have
    # performance-update obligations. Approved full-day leave is also excluded.
    yesterday_rows = (
        client.table("performance_updates")
        .select("employee_id, submitted_at")
        .eq("work_date", yesterday.isoformat())
        .execute().data
        or []
    )
    submitted_yesterday_ids = {r["employee_id"] for r in yesterday_rows if r.get("submitted_at")}
    yesterday_leave_rows = (
        client.table("employee_leaves")
        .select("employee_id,leave_type")
        .eq("leave_date", yesterday.isoformat())
        .eq("status", "approved")
        .execute().data or []
    )
    yesterday_full_leave_ids = {
        r["employee_id"] for r in yesterday_leave_rows if r.get("leave_type") != "half_day"
    }
    eligible_for_yesterday = [
        e for e in active_employees
        if (not e.get("joining_date") or e["joining_date"] <= yesterday.isoformat())
        and e["id"] not in yesterday_full_leave_ids
    ]
    missing_performance_count = sum(
        1 for e in eligible_for_yesterday if e["id"] not in submitted_yesterday_ids
    )

    # Laptop inactivity is an employee-only monitoring metric.
    inactivity_flags_count = 0
    for row in today_attendance:
        employee = next((e for e in active_employees if e["id"] == row.get("employee_id")), None)
        if not employee:
            continue
        summary = activity_service.get_activity_summary_for_attendance(row, settings)
        if summary["flagged"]:
            inactivity_flags_count += 1

    return {
        "total_employees": total_staff,
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
    attendance_staff = _get_active_attendance_staff()
    attendance_by_id = {e["id"]: e for e in attendance_staff}
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
    # Attendance drill-downs include Employees + Admins; performance and
    # inactivity drill-downs remain employee-only.
    today_rows = [r for r in today_rows if r.get("employee_id") in attendance_by_id]

    if metric == "not_checked_in":
        checked_ids = {r["employee_id"] for r in today_rows}
        approved_leave_rows = (
            client.table("employee_leaves")
            .select("employee_id,leave_type")
            .eq("leave_date", today.isoformat())
            .eq("status", "approved")
            .execute().data or []
        )
        leave_ids = {r["employee_id"] for r in approved_leave_rows if r.get("leave_type") != "half_day"}
        remote_rows = (
            client.table("remote_work_requests")
            .select("employee_id,work_mode")
            .eq("work_date", today.isoformat())
            .in_("status", ["approved", "assigned", "started"])
            .execute().data or []
        )
        other_site_ids = {r["employee_id"] for r in remote_rows if r.get("work_mode") == "other_site"}
        on_duty_rows = (
            client.table("on_duty_requests")
            .select("employee_id")
            .eq("on_duty_date", today.isoformat())
            .in_("status", ["approved", "started", "completed"])
            .execute().data or []
        )
        on_duty_ids = {r["employee_id"] for r in on_duty_rows}
        exempt_ids = leave_ids | other_site_ids | on_duty_ids
        rows = []
        for employee in attendance_staff:
            if employee["id"] not in checked_ids and employee["id"] not in exempt_ids:
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
            if attendance["employee_id"] not in active_by_id:
                continue
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
        employee = attendance_by_id.get(attendance["employee_id"])
        if not employee:
            continue
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
    if status and status not in {"wfh", "other_site"}:
        query = query.eq("status", status)
    if source:
        query = query.eq("check_in_source", source)
    rows = query.execute().data or []

    # Include inactive employees too — historical attendance rows must
    # still display correctly for someone who has since been disabled.
    employees = {e["id"]: e for e in _get_all_employees()}

    remote_query = client.table("remote_work_requests").select(
        "id,employee_id,work_date,work_mode,site_name,purpose,status,planned_start,planned_end,approved_by,assignment_source"
    ).in_("status", ["approved", "assigned", "started"])
    if on_date:
        remote_query = remote_query.eq("work_date", on_date.isoformat())
    if employee_id:
        remote_query = remote_query.eq("employee_id", employee_id)
    remote_rows = remote_query.execute().data or []
    remote_by_key = {(r["employee_id"], r["work_date"]): r for r in remote_rows}

    enriched = []
    seen_remote_keys = set()
    for row in rows:
        emp = employees.get(row["employee_id"], {})
        if department and emp.get("department") != department:
            continue

        remote = remote_by_key.get((row["employee_id"], row["attendance_date"]))
        if status in {"wfh", "other_site"} and (not remote or remote.get("work_mode") != status):
            continue
        if source and source != row.get("check_in_source"):
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
                "remote_work": remote,
                "work_mode": remote.get("work_mode") if remote else None,
                "work_location": ("Work From Home" if remote and remote.get("work_mode") == "wfh" else remote.get("site_name") if remote else None),
                "total_session_seconds": summary["total_session_seconds"],
                "counted_inactivity_seconds": summary["counted_inactivity_seconds"],
                "active_session_seconds": summary["active_session_seconds"],
                "total_break_seconds": break_summary["total_break_seconds"],
                "breaks": break_summary["sessions"],
                "inactivity_flag": summary["flagged"],
                "checkout_missed": checkout_missed,
                "target_work_seconds": 0 if remote and remote.get("work_mode") == "other_site" else 8 * 3600,
                "work_status": "not_required" if remote and remote.get("work_mode") == "other_site" else None,
            }
        )
        if remote:
            seen_remote_keys.add((row["employee_id"], row["attendance_date"]))

    # Other Site intentionally has no attendance punch, so create a visible
    # attendance-section row for approved/assigned work even when there is
    # no attendance record. WFH is also surfaced when it has not yet been
    # punched, so the attendance page clearly shows the assigned work mode.
    for remote in remote_rows:
        key = (remote["employee_id"], remote["work_date"])
        if key in seen_remote_keys:
            continue
        emp = employees.get(remote["employee_id"], {})
        if department and emp.get("department") != department:
            continue
        if status and status not in {"wfh", "other_site"}:
            continue
        if status in {"wfh", "other_site"} and remote.get("work_mode") != status:
            continue
        if source:
            # A remote-only row has no GPS/WiFi/Admin punch source.
            continue
        row_status = "other_site" if remote.get("work_mode") == "other_site" else "wfh"
        enriched.append({
            "id": f"remote:{remote['id']}",
            "employee_id": remote["employee_id"],
            "employee_name": emp.get("name"),
            "employee_code": emp.get("employee_code"),
            "department": emp.get("department"),
            "attendance_date": remote["work_date"],
            "check_in": None,
            "check_out": None,
            "checkout_missed": False,
            "status": row_status,
            "check_in_source": None,
            "check_out_source": None,
            "remote_work": remote,
            "work_mode": remote.get("work_mode"),
            "work_location": "Work From Home" if remote.get("work_mode") == "wfh" else remote.get("site_name"),
            "total_session_seconds": 0,
            "counted_inactivity_seconds": 0,
            "active_session_seconds": 0,
            "total_break_seconds": 0,
            "breaks": [],
            "inactivity_flag": False,
            "target_work_seconds": 0 if remote.get("work_mode") == "other_site" else 8 * 3600,
            "work_status": "not_required" if remote.get("work_mode") == "other_site" else "not_checked_in",
        })

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
