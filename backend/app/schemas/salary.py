"""Salary calculation request/response schemas."""
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class SalaryCalculateRequest(BaseModel):
    employee_id: str
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
    # Optional so the saved staff default salary can be used automatically.
    salary: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)


class SalaryCalculationResponse(BaseModel):
    id: str | None = None
    employee_id: str
    employee_name: str
    employee_code: str | None = None
    role: str
    year: int
    month: int
    salary: Decimal
    total_days_in_month: int
    elapsed_days_considered: int
    working_days: int
    holidays: int
    sundays: int
    other_non_working_days: int
    paid_leave_days: Decimal
    sick_leave_days: Decimal
    unpaid_leave_days: Decimal
    unpaid_half_leave_days: Decimal
    other_site_days: int
    on_duty_days: int
    short_8h_days: int
    short_day_penalty_days: Decimal
    deduction_days: Decimal
    per_day_salary: Decimal
    deduction_amount: Decimal
    payable_salary: Decimal
    details: list[dict]
    calculated_at: datetime | None = None


class SalaryBaseUpdateRequest(BaseModel):
    employee_id: str
    salary: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class SalaryBaseResponse(BaseModel):
    employee_id: str
    employee_name: str
    employee_code: str | None = None
    role: str
    monthly_salary: Decimal | None = None
