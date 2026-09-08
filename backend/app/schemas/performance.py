"""Pydantic schemas for daily performance updates."""

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel

PerformanceStatus = Literal["not_available", "available", "submitted", "missing", "backdated"]


class PerformanceSubmission(BaseModel):
    """
    Body for POST /api/performance. work_date is optional — omit it to
    submit for today; the only other value the backend accepts here is
    yesterday's date (see performance_service.submit_performance for why
    older dates are rejected).
    """

    work_date: Optional[date] = None
    performance_text: Optional[str] = None
    completed_tasks: Optional[str] = None
    pending_tasks: Optional[str] = None
    blockers: Optional[str] = None
    additional_notes: Optional[str] = None


class PerformanceRecord(BaseModel):
    id: str
    employee_id: str
    work_date: date
    performance_text: Optional[str] = None
    completed_tasks: Optional[str] = None
    pending_tasks: Optional[str] = None
    blockers: Optional[str] = None
    additional_notes: Optional[str] = None
    status: PerformanceStatus
    available_from: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
