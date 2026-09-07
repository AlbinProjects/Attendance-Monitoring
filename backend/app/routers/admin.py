"""
Admin router.

Every route requires admin or super_admin — enforced by require_role, so a
regular employee hitting these by hand always gets 403 regardless of what
the frontend renders.
"""

from datetime import date as date_cls
from typing import Optional

from fastapi import APIRouter, Depends, Request, Response

from app.config import get_settings
from app.dependencies import require_role
from app.schemas.admin import CompanySettingsUpdateRequest, DashboardStats
from app.schemas.attendance import AttendanceCorrectionRequest, ManualAttendanceCreateRequest
from app.services import (
    activity_service,
    admin_service,
    attendance_service,
    audit_service,
    company_config_service,
    network_service,
    reports_service,
)
from app.services.time_service import get_office_today

router = APIRouter()


@router.get("/dashboard", response_model=DashboardStats)
async def dashboard(_employee: dict = Depends(require_role("admin", "super_admin"))):
    settings = get_settings()
    return admin_service.get_dashboard_stats(settings)


@router.get("/attendance")
async def attendance_table(
    _employee: dict = Depends(require_role("admin", "super_admin")),
    date: Optional[date_cls] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    inactivity_flag: Optional[bool] = None,
):
    settings = get_settings()
    return admin_service.get_admin_attendance(
        settings,
        on_date=date,
        employee_id=employee_id,
        department=department,
        status=status,
        source=source,
        inactivity_flag=inactivity_flag,
    )


@router.get("/performance")
async def performance_table(
    _employee: dict = Depends(require_role("admin", "super_admin")),
    date: Optional[date_cls] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
):
    settings = get_settings()
    return admin_service.get_admin_performance(
        settings, on_date=date, employee_id=employee_id, department=department, status=status
    )


@router.get("/activity")
async def activity_table(
    _employee: dict = Depends(require_role("admin", "super_admin")),
    date: Optional[date_cls] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    flag: Optional[bool] = None,
):
    settings = get_settings()
    return admin_service.get_admin_activity(
        settings, on_date=date, employee_id=employee_id, department=department, flag=flag
    )


@router.get("/activity/{attendance_id}/periods")
async def activity_periods(
    attendance_id: str,
    _employee: dict = Depends(require_role("admin", "super_admin")),
):
    """Detail drill-down: the individual inactivity periods behind one
    day's summary (README section 39 — "Admin can click an employee to
    see inactivity periods")."""
    return activity_service.get_periods_for_attendance(attendance_id)


@router.post("/attendance/manual")
async def create_manual_attendance(
    payload: ManualAttendanceCreateRequest,
    request: Request,
    employee: dict = Depends(require_role("admin", "super_admin")),
):
    """
    Exceptional attendance for when normal check-in wasn't possible
    (README section 19 — WiFi/GPS unavailable, forgotten check-in, other
    authorized case). Deliberately NOT gated by GPS location verification
    (unlike normal employee check-in/check-out) — an admin correcting a
    record is often doing so precisely because the employee couldn't get a
    usable GPS reading, or is entering it from off-site entirely.
    """
    settings = get_settings()
    ip_address = network_service.get_verified_client_ip(request)
    return attendance_service.create_manual_attendance(
        employee_id=payload.employee_id,
        attendance_date=payload.attendance_date,
        check_in_time=payload.check_in_time,
        check_out_time=payload.check_out_time,
        reason=payload.reason,
        marked_by_employee_id=employee["id"],
        ip_address=ip_address,
        settings=settings,
    )


@router.put("/attendance/{attendance_id}")
async def correct_attendance(
    attendance_id: str,
    payload: AttendanceCorrectionRequest,
    request: Request,
    employee: dict = Depends(require_role("admin", "super_admin")),
):
    """Correct an existing attendance record — history is never silently
    overwritten; see attendance_service.update_attendance_by_id for the
    audit trail this always produces."""
    settings = get_settings()
    ip_address = network_service.get_verified_client_ip(request)
    return attendance_service.update_attendance_by_id(
        attendance_id=attendance_id,
        check_in_time=payload.check_in_time,
        check_out_time=payload.check_out_time,
        reason=payload.reason,
        performed_by_employee_id=employee["id"],
        ip_address=ip_address,
        settings=settings,
    )


@router.get("/audit")
async def audit_logs(
    _employee: dict = Depends(require_role("admin", "super_admin")),
    employee_id: Optional[str] = None,
    action: Optional[str] = None,
    date: Optional[date_cls] = None,
):
    """Read-only audit trail. Employees cannot reach this route at all
    (require_role blocks them at 403); there is no delete path anywhere
    in the backend for audit rows."""
    return audit_service.get_audit_logs(
        employee_id=employee_id, action=action, on_date=date.isoformat() if date else None
    )


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/attendance")
async def export_attendance_csv(
    _employee: dict = Depends(require_role("admin", "super_admin")),
    date: Optional[date_cls] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
    source: Optional[str] = None,
    inactivity_flag: Optional[bool] = None,
):
    """Same filters as GET /attendance — the export always reflects
    exactly what's currently on screen in the admin attendance table."""
    settings = get_settings()
    content = reports_service.generate_attendance_csv(
        settings,
        on_date=date,
        employee_id=employee_id,
        department=department,
        status=status,
        source=source,
        inactivity_flag=inactivity_flag,
    )
    return _csv_response(content, f"attendance_report_{get_office_today(settings).isoformat()}.csv")


@router.get("/reports/performance")
async def export_performance_csv(
    _employee: dict = Depends(require_role("admin", "super_admin")),
    date: Optional[date_cls] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
):
    settings = get_settings()
    content = reports_service.generate_performance_csv(
        settings, on_date=date, employee_id=employee_id, department=department, status=status
    )
    return _csv_response(content, f"performance_report_{get_office_today(settings).isoformat()}.csv")


@router.get("/reports/activity")
async def export_activity_csv(
    _employee: dict = Depends(require_role("admin", "super_admin")),
    date: Optional[date_cls] = None,
    employee_id: Optional[str] = None,
    department: Optional[str] = None,
    flag: Optional[bool] = None,
):
    settings = get_settings()
    content = reports_service.generate_activity_csv(
        settings, on_date=date, employee_id=employee_id, department=department, flag=flag
    )
    return _csv_response(content, f"activity_report_{get_office_today(settings).isoformat()}.csv")


@router.get("/settings")
async def get_company_settings(_employee: dict = Depends(require_role("admin", "super_admin"))):
    """
    Read-only for admin, editable for super_admin (README section 12 —
    'Configure company settings' / 'Configure company allowed IPs' are
    Super Admin capabilities). Returns the full company_settings row,
    including network_mode, office location, and thresholds carried over
    from earlier phases (performance/inactivity settings).
    """
    return company_config_service.get_raw_company_settings()


@router.put("/settings")
async def update_company_settings(
    payload: CompanySettingsUpdateRequest,
    request: Request,
    employee: dict = Depends(require_role("super_admin")),
):
    """
    Super-Admin-only. Lets a Super Admin choose 'static' (IP + GPS both
    required) vs 'dynamic' (GPS only) network mode, and set the office
    GPS location/radius/accuracy threshold and laptop-presence freshness
    window at runtime — no redeploy needed. Always audited.
    """
    ip_address = network_service.get_verified_client_ip(request)
    return company_config_service.update_company_settings(
        payload.model_dump(exclude_unset=True), employee["id"], ip_address
    )
