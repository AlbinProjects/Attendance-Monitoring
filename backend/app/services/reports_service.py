"""
CSV report generation for the admin dashboard (README section 61).

Reuses the same filtered queries as the admin tables (admin_service) so a
report always reflects exactly what an admin sees on screen, filtered the
same way — there is no separate, potentially inconsistent code path for
"what goes in the export" vs. "what's shown in the table".
"""

import csv
import io
from datetime import datetime
from typing import List, Optional

from app.config import Settings
from app.services import admin_service


def _format_duration(total_seconds: Optional[int]) -> str:
    if total_seconds is None:
        return ""
    total_seconds = int(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def _format_time(iso_string: Optional[str]) -> str:
    if not iso_string:
        return ""
    return datetime.fromisoformat(iso_string).strftime("%H:%M")


def _format_datetime(iso_string: Optional[str]) -> str:
    if not iso_string:
        return ""
    return datetime.fromisoformat(iso_string).strftime("%Y-%m-%d %H:%M")


def _rows_to_csv(header: List[str], rows: List[List[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def generate_attendance_csv(
    settings: Settings,
    *,
    on_date=None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    inactivity_flag: Optional[bool] = None,
) -> str:
    records = admin_service.get_admin_attendance(
        settings,
        on_date=on_date,
        employee_id=employee_id,
        department=department,
        status=status,
        source=source,
        inactivity_flag=inactivity_flag,
    )
    header = ["Employee", "Department", "Date", "Check In", "Check Out", "Status", "Source", "Active Time", "Inactivity"]
    rows = [
        [
            r.get("employee_name") or "",
            r.get("department") or "",
            r.get("attendance_date") or "",
            _format_time(r.get("check_in")),
            _format_time(r.get("check_out")),
            r.get("status") or "",
            r.get("check_in_source") or "",
            _format_duration(r.get("active_session_seconds")),
            _format_duration(r.get("counted_inactivity_seconds")),
        ]
        for r in records
    ]
    return _rows_to_csv(header, rows)


def generate_performance_csv(
    settings: Settings,
    *,
    on_date=None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
) -> str:
    records = admin_service.get_admin_performance(
        settings, on_date=on_date, employee_id=employee_id, department=department, status=status
    )
    header = ["Employee", "Department", "Work Date", "Status", "Submitted At", "Performance"]
    rows = [
        [
            r.get("employee_name") or "",
            r.get("department") or "",
            r.get("work_date") or "",
            r.get("status") or "",
            _format_datetime(r.get("submitted_at")),
            (r.get("performance_text") or "").replace("\n", " ").replace("\r", " "),
        ]
        for r in records
    ]
    return _rows_to_csv(header, rows)


def generate_activity_csv(
    settings: Settings,
    *,
    on_date=None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    flag: Optional[bool] = None,
) -> str:
    records = admin_service.get_admin_activity(
        settings, on_date=on_date, employee_id=employee_id, department=department, flag=flag
    )
    header = ["Employee", "Date", "Total Session", "Counted Inactivity", "Active Time", "Flag"]
    rows = [
        [
            r.get("employee_name") or "",
            r.get("attendance_date") or "",
            _format_duration(r.get("total_session_seconds")),
            _format_duration(r.get("counted_inactivity_seconds")),
            _format_duration(r.get("active_session_seconds")),
            "Flagged" if r.get("flagged") else "Normal",
        ]
        for r in records
    ]
    return _rows_to_csv(header, rows)
