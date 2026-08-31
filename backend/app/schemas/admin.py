"""Pydantic schemas for admin endpoints."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["employee", "admin", "super_admin"]


class EmployeeCreateRequest(BaseModel):
    employee_code: str
    name: str
    email: str
    department: Optional[str] = None
    designation: Optional[str] = None
    role: Role = "employee"
    joining_date: Optional[date] = None
    # If omitted, a random temporary password is generated and returned
    # once in the response for the Super Admin to relay out-of-band.
    password: Optional[str] = None


class EmployeeUpdateRequest(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    joining_date: Optional[date] = None
    role: Optional[Role] = None
    is_active: Optional[bool] = None


class DashboardStats(BaseModel):
    total_employees: int
    present_today: int
    late_today: int
    half_day_today: int
    manual_today: int
    absent_today: int
    missing_performance_count: int
    inactivity_flags_count: int


NetworkMode = Literal["static", "dynamic"]


class CompanySettingsUpdateRequest(BaseModel):
    """
    Super-Admin-only (Phase 14). Every field is optional — only what's
    provided is changed, everything else keeps its current value. Setting
    a field to null does NOT clear it (see company_config_service.
    update_company_settings) — there's currently no self-service "revert
    to env default" action; that's a documented follow-up, not an
    oversight.
    """

    network_mode: Optional[NetworkMode] = None
    allowed_ips: Optional[list[str]] = None
    office_latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    office_longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    office_gps_radius_meters: Optional[float] = Field(default=None, gt=0)
    max_gps_accuracy_meters: Optional[float] = Field(default=None, gt=0)
    laptop_presence_freshness_minutes: Optional[int] = Field(default=None, gt=0)
