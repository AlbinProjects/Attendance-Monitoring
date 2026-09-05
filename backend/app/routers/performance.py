"""
Performance router.

Employees can only ever act on their own performance — employee_id is
always derived from get_current_employee, never accepted in the request
body, matching every other write path in this app.
"""

from datetime import date as date_cls

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.dependencies import get_current_employee
from app.schemas.performance import PerformanceSubmission
from app.services import performance_service

router = APIRouter()


@router.get("/today")
async def get_today(employee: dict = Depends(get_current_employee)):
    """
    Current status of today's report: not_available (before 5 PM),
    available (5 PM has passed, not yet submitted), or submitted.
    """
    settings = get_settings()
    return performance_service.get_today_status(employee["id"], settings)


@router.post("")
async def submit(
    payload: PerformanceSubmission,
    employee: dict = Depends(get_current_employee),
):
    """
    Submit (or backdate-submit) a performance report. See
    performance_service.submit_performance for the exact date rules —
    today (if available), or yesterday, only.
    """
    settings = get_settings()
    fields = payload.model_dump(exclude={"work_date"})
    return performance_service.submit_performance(employee["id"], payload.work_date, fields, settings)


@router.get("/history")
async def get_history(employee: dict = Depends(get_current_employee)):
    """Performance history from September 1, 2026 onward."""
    settings = get_settings()
    return performance_service.get_history(
        employee["id"],
        settings,
    )


@router.get("/missing")
async def get_missing(employee: dict = Depends(get_current_employee)):
    """Past dates with no submitted performance — powers the post-login
    missing-performance warning (README section 26-27)."""
    settings = get_settings()
    joining_date = employee.get("joining_date")
    if isinstance(joining_date, str):
        joining_date = date_cls.fromisoformat(joining_date)
    return performance_service.get_missing_dates(employee["id"], settings, joining_date=joining_date)
