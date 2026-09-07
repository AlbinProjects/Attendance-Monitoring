"""Company calendar and leave API."""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_employee, require_role
from app.services import calendar_service, on_duty_service, remote_work_service
from app.services.time_service import get_office_today
from app.config import get_settings

router = APIRouter()

@router.get("/today")
async def get_today_calendar(employee: dict = Depends(get_current_employee)):
    return calendar_service.get_day_status(get_office_today(get_settings()))

@router.get("/month")
async def get_month_calendar(year: int = Query(..., ge=2020, le=2100), month: int = Query(..., ge=1, le=12), employee: dict = Depends(get_current_employee)):
    return calendar_service.get_month_calendar(year, month)

@router.get("/date/{calendar_date}")
async def get_calendar_date(calendar_date: date, employee: dict = Depends(get_current_employee)):
    return calendar_service.get_day_status(calendar_date)

@router.put("/admin/date/{calendar_date}", dependencies=[Depends(require_role("admin", "super_admin"))])
async def set_calendar_date(calendar_date: date, day_type: str, is_working_day: bool, name: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return calendar_service.set_calendar_date(calendar_date, day_type, is_working_day, name, employee["id"])

@router.get("/leave")
async def get_my_leave(start_date: Optional[date] = None, end_date: Optional[date] = None, employee: dict = Depends(get_current_employee)):
    return calendar_service.get_employee_leaves(employee["id"], start_date, end_date)

@router.get("/leave/balance")
async def get_my_leave_balance(employee: dict = Depends(get_current_employee)):
    return calendar_service.get_leave_balance(employee["id"])

@router.get("/leave/{leave_date}")
async def get_my_leave_for_date(leave_date: date, employee: dict = Depends(get_current_employee)):
    return calendar_service.get_leave_for_employee_date(employee["id"], leave_date)

@router.get("/admin/leave", dependencies=[Depends(require_role("admin", "super_admin"))])
async def get_all_employee_leaves(start_date: Optional[date] = None, end_date: Optional[date] = None, employee_id: Optional[str] = None, status_filter: Optional[str] = Query(None, alias="status"), employee: dict = Depends(get_current_employee)):
    return calendar_service.get_all_leaves(start_date, end_date, employee_id, status_filter)

@router.post("/leave/request")
async def request_leave(leave_date: date, leave_type: str, reason: str, employee: dict = Depends(require_role("employee", "admin"))):
    return calendar_service.request_leave(employee["id"], leave_date, leave_type, reason)

@router.post("/admin/leave/{leave_id}/approve", dependencies=[Depends(require_role("admin", "super_admin"))])
async def approve_leave_request(leave_id: str, employee: dict = Depends(get_current_employee)):
    return calendar_service.approve_leave_request(leave_id, employee["id"])

@router.post("/admin/leave/{leave_id}/reject", dependencies=[Depends(require_role("admin", "super_admin"))])
async def reject_leave_request(leave_id: str, reason: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return calendar_service.reject_leave_request(leave_id, employee["id"], reason)



@router.get("/on-duty")
async def get_my_on_duty(status: Optional[str] = None, employee: dict = Depends(require_role("employee", "admin"))):
    return on_duty_service.get_my_requests(employee["id"], status)

@router.get("/on-duty/today")
async def get_my_on_duty_today(employee: dict = Depends(require_role("employee", "admin"))):
    return on_duty_service.get_today(employee["id"])

@router.post("/on-duty/request")
async def request_on_duty(on_duty_date: date, purpose: str, planned_start: Optional[str] = None, planned_end: Optional[str] = None, employee: dict = Depends(require_role("employee", "admin"))):
    from datetime import time as _time
    def parse(v):
        return _time.fromisoformat(v) if v else None
    return on_duty_service.request_on_duty(employee["id"], on_duty_date, purpose, parse(planned_start), parse(planned_end))

@router.post("/on-duty/start")
async def start_on_duty(employee: dict = Depends(require_role("employee", "admin"))):
    return on_duty_service.start_today(employee["id"])

@router.post("/on-duty/end")
async def end_on_duty(employee: dict = Depends(require_role("employee", "admin"))):
    return on_duty_service.end_today(employee["id"])

@router.get("/admin/on-duty", dependencies=[Depends(require_role("admin", "super_admin"))])
async def get_pending_on_duty(employee: dict = Depends(get_current_employee)):
    return on_duty_service.get_pending()

@router.post("/admin/on-duty/{request_id}/approve", dependencies=[Depends(require_role("admin", "super_admin"))])
async def approve_on_duty(request_id: str, employee: dict = Depends(get_current_employee)):
    return on_duty_service.approve(request_id, employee["id"])

@router.post("/admin/on-duty/{request_id}/reject", dependencies=[Depends(require_role("admin", "super_admin"))])
async def reject_on_duty(request_id: str, reason: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return on_duty_service.reject(request_id, employee["id"], reason)

@router.post("/admin/on-duty", dependencies=[Depends(require_role("super_admin"))])
async def direct_on_duty(employee_id: str, on_duty_date: date, purpose: str, planned_start: Optional[str] = None, planned_end: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    from datetime import time as _time
    def parse(v):
        return _time.fromisoformat(v) if v else None
    return on_duty_service.direct_grant(employee_id, on_duty_date, purpose, parse(planned_start), parse(planned_end), employee["id"])



@router.get("/remote-work")
async def get_my_remote_work(status: Optional[str] = None, employee: dict = Depends(require_role("employee", "admin"))):
    return remote_work_service.get_my(employee["id"], status)

@router.get("/remote-work/today")
async def get_my_remote_work_today(employee: dict = Depends(require_role("employee", "admin"))):
    return remote_work_service.get_today(employee["id"])

@router.post("/remote-work/request")
async def request_remote_work(work_mode: str, work_date: date, purpose: str, planned_start: Optional[str] = None, planned_end: Optional[str] = None, site_name: Optional[str] = None, employee: dict = Depends(require_role("employee", "admin"))):
    from datetime import time as _time
    def parse(v): return _time.fromisoformat(v) if v else None
    return remote_work_service.request(employee["id"], work_mode, work_date, purpose, parse(planned_start), parse(planned_end), site_name)

@router.put("/remote-work/{request_id}")
async def edit_remote_work(request_id: str, work_mode: str, work_date: date, purpose: str, planned_start: Optional[str] = None, planned_end: Optional[str] = None, site_name: Optional[str] = None, employee: dict = Depends(require_role("employee", "admin", "super_admin"))):
    from datetime import time as _time
    def parse(v): return _time.fromisoformat(v) if v else None
    return remote_work_service.edit(request_id, employee["id"], work_mode, work_date, purpose, parse(planned_start), parse(planned_end), site_name)

@router.delete("/remote-work/{request_id}")
async def cancel_remote_work(request_id: str, employee: dict = Depends(require_role("employee", "admin", "super_admin"))):
    return remote_work_service.cancel(request_id, employee["id"])

@router.get("/admin/remote-work", dependencies=[Depends(require_role("admin", "super_admin"))])
async def get_pending_remote_work(employee: dict = Depends(get_current_employee)):
    return remote_work_service.get_pending()

@router.get("/admin/remote-work/all", dependencies=[Depends(require_role("admin", "super_admin"))])
async def get_all_remote_work(status: Optional[str] = None, employee_id: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    # Admin-facing history/upcoming view; pending rows are expired to not_approved before returning.
    remote_work_service._expire_pending_for_employee()
    q = remote_work_service.get_service_client().table("remote_work_requests").select("*").order("work_date", desc=True)
    if status: q = q.eq("status", status)
    if employee_id: q = q.eq("employee_id", employee_id)
    return q.execute().data or []

@router.post("/admin/remote-work/{request_id}/approve", dependencies=[Depends(require_role("admin", "super_admin"))])
async def approve_remote_work(request_id: str, employee: dict = Depends(get_current_employee)):
    return remote_work_service.approve(request_id, employee["id"])

@router.post("/admin/remote-work/{request_id}/reject", dependencies=[Depends(require_role("admin", "super_admin"))])
async def reject_remote_work(request_id: str, reason: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return remote_work_service.reject(request_id, employee["id"], reason)

@router.post("/admin/remote-work")
async def assign_remote_work(work_mode: str, employee_id: str, work_date: date, purpose: str, planned_start: Optional[str] = None, planned_end: Optional[str] = None, site_name: Optional[str] = None, employee: dict = Depends(require_role("admin", "super_admin"))):
    from datetime import time as _time
    def parse(v): return _time.fromisoformat(v) if v else None
    return remote_work_service.direct_assign(employee_id, work_mode, work_date, purpose, parse(planned_start), parse(planned_end), site_name, employee["id"])

@router.post("/admin/leave", dependencies=[Depends(require_role("admin", "super_admin"))])
async def grant_employee_leave(employee_id: str, leave_date: date, leave_type: str, is_additional: bool = False, reason: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return calendar_service.grant_leave(employee_id, leave_date, leave_type, is_additional, reason, employee["id"])

@router.delete("/admin/leave/{leave_id}", dependencies=[Depends(require_role("admin", "super_admin"))])
async def cancel_employee_leave(leave_id: str, reason: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return calendar_service.cancel_leave(leave_id, employee["id"], reason)
