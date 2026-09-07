"""Company calendar and leave API."""
from datetime import date
from typing import Optional
from fastapi import APIRouter, Depends, Query
from app.dependencies import get_current_employee, require_role
from app.services import calendar_service
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
async def get_all_employee_leaves(start_date: Optional[date] = None, end_date: Optional[date] = None, employee_id: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return calendar_service.get_all_leaves(start_date, end_date, employee_id)

@router.post("/admin/leave", dependencies=[Depends(require_role("admin", "super_admin"))])
async def grant_employee_leave(employee_id: str, leave_date: date, leave_type: str, is_additional: bool = False, reason: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return calendar_service.grant_leave(employee_id, leave_date, leave_type, is_additional, reason, employee["id"])

@router.delete("/admin/leave/{leave_id}", dependencies=[Depends(require_role("admin", "super_admin"))])
async def cancel_employee_leave(leave_id: str, reason: Optional[str] = None, employee: dict = Depends(get_current_employee)):
    return calendar_service.cancel_leave(leave_id, employee["id"], reason)
