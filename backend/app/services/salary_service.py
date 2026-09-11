"""Monthly salary calculation for Employees and Admins.

Salary deductions are intentionally transparent and calendar-day based:
- full approved unpaid leave = 1 deduction day
- approved half-day leave = 0.5 deduction day
- if more than 3 completed/elapsed working days in the month are below the
  8-hour target, add exactly 0.5 deduction day
- Other Site and On Duty are exempt from the 8-hour short-day rule
- Sundays/holidays/other non-working days are not short-work days
- the salary divisor is the total calendar days in the month, including
  Sundays and holidays, as requested by the business rule.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List

from fastapi import HTTPException, status

from app.config import Settings
from app.services import attendance_service, audit_service, calendar_service
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_now, get_office_today

MONEY = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def _target_employee(employee_id: str) -> Dict[str, Any]:
    result = (
        get_service_client().table("employees")
        .select("id,name,employee_code,role,is_active,joining_date,monthly_salary")
        .eq("id", employee_id)
        .maybe_single()
        .execute()
    )
    if result is None or not result.data or not result.data.get("is_active"):
        raise HTTPException(status_code=404, detail="Employee or Admin not found or inactive.")
    row = result.data
    if row.get("role") not in {"employee", "admin"}:
        raise HTTPException(status_code=400, detail="Salary can only be calculated for an Employee or Admin.")
    return row


def get_base(employee_id: str) -> Dict[str, Any]:
    target = _target_employee(employee_id)
    return {
        "employee_id": target["id"],
        "employee_name": target.get("name"),
        "employee_code": target.get("employee_code"),
        "role": target.get("role"),
        "monthly_salary": target.get("monthly_salary"),
    }


def set_base(employee_id: str, salary: Decimal, performed_by: str) -> Dict[str, Any]:
    if salary <= 0:
        raise HTTPException(status_code=400, detail="Salary must be greater than zero.")
    target = _target_employee(employee_id)
    old_salary = target.get("monthly_salary")
    client = get_service_client()
    result = (
        client.table("employees")
        .update({"monthly_salary": _money(Decimal(salary))})
        .eq("id", employee_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Employee or Admin not found.")
    audit_service.write_audit_log(
        action="SALARY_BASE_UPDATED",
        employee_id=employee_id,
        old_value={"monthly_salary": str(old_salary)} if old_salary is not None else None,
        new_value={"monthly_salary": str(_money(Decimal(salary)))},
        performed_by=performed_by,
        reason="Default monthly salary changed",
    )
    return get_base(employee_id)


def _get_on_duty_ids(employee_id: str, start: date, end: date) -> set[str]:
    rows = (
        get_service_client().table("on_duty_requests")
        .select("on_duty_date,status")
        .eq("employee_id", employee_id)
        .gte("on_duty_date", start.isoformat())
        .lte("on_duty_date", end.isoformat())
        .in_("status", ["approved", "started", "completed"])
        .execute().data or []
    )
    return {r["on_duty_date"] for r in rows}


def _saved(employee_id: str, year: int, month: int) -> Dict[str, Any] | None:
    result = (
        get_service_client().table("salary_calculations")
        .select("*")
        .eq("employee_id", employee_id)
        .eq("salary_year", year)
        .eq("salary_month", month)
        .maybe_single().execute()
    )
    return result.data if result is not None else None


def get_saved(employee_id: str, year: int, month: int) -> Dict[str, Any] | None:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month.")
    target = _target_employee(employee_id)
    row = _saved(employee_id, year, month)
    if not row:
        return None
    return _response_from_row(row, target)


def calculate(employee_id: str, year: int, month: int, salary: Decimal | None,
              performed_by: str, settings: Settings) -> Dict[str, Any]:
    if month < 1 or month > 12:
        raise HTTPException(status_code=400, detail="Invalid month.")

    target = _target_employee(employee_id)
    # A salary supplied by the administrator becomes the persistent default.
    # If omitted, use the saved default salary for this staff member.
    if salary is None:
        salary = target.get("monthly_salary")
    if salary is None or Decimal(salary) <= 0:
        raise HTTPException(status_code=400, detail="Set a monthly salary for this Employee/Admin before calculating.")
    salary = Decimal(salary)

    # Persist the current salary so future months pre-fill automatically.
    if target.get("monthly_salary") is None or Decimal(str(target.get("monthly_salary"))) != salary:
        set_base(employee_id, salary, performed_by)
        target["monthly_salary"] = _money(salary)
    today = get_office_today(settings)
    month_start = date(year, month, 1)
    month_end = date(year, month, monthrange(year, month)[1])
    total_days = monthrange(year, month)[1]

    # For a future month there are no elapsed workdays yet. For the current
    # month, only dates through today are evaluated. A past month is complete.
    considered_end = min(month_end, today)
    elapsed_days = 0 if considered_end < month_start else (considered_end - month_start).days + 1

    # Reuse the authoritative monthly attendance calculation so breaks,
    # missed check-outs, WFH and Other Site all follow the same rules as the
    # Attendance screen. The service also applies the existing 4 PM automatic
    # unpaid-leave rule to Employees where appropriate.
    month_rows = attendance_service.get_monthly_attendance(employee_id, year, month, settings)
    on_duty_ids = _get_on_duty_ids(employee_id, month_start, month_end)

    counts = {
        "working_days": 0,
        "holidays": 0,
        "sundays": 0,
        "other_non_working_days": 0,
        "paid_leave_days": Decimal("0"),
        "sick_leave_days": Decimal("0"),
        "unpaid_leave_days": Decimal("0"),
        "unpaid_half_leave_days": Decimal("0"),
        "other_site_days": 0,
        "on_duty_days": 0,
        "short_8h_days": 0,
    }
    details: List[Dict[str, Any]] = []

    for item in month_rows:
        d = date.fromisoformat(item["date"])
        iso = item["date"]
        cal = item.get("calendar") or {}
        day_type = cal.get("day_type")
        leave = item.get("leave")
        remote = item.get("remote_work")
        remote_mode = item.get("work_mode")
        is_elapsed = d <= considered_end
        # Future days are displayed but cannot produce deductions.
        if d > considered_end:
            continue

        if day_type == "sunday":
            counts["sundays"] += 1
            continue
        if day_type == "holiday":
            counts["holidays"] += 1
            continue
        if not cal.get("is_working_day"):
            counts["other_non_working_days"] += 1
            continue

        # Joining-date protection: a date before joining is not a workday for
        # this person, although it remains in the calendar denominator.
        joining_date = target.get("joining_date")
        if joining_date and d < date.fromisoformat(joining_date):
            continue

        if leave:
            leave_type = leave.get("leave_type")
            if leave_type == "half_day":
                counts["unpaid_half_leave_days"] += Decimal("0.5")
                details.append({
                    "date": iso, "type": "unpaid_half_leave", "deduction_days": 0.5,
                    "reason": leave.get("reason") or "Approved half-day leave",
                    "half_day_period": leave.get("half_day_period"),
                })
                continue
            if leave_type == "unpaid":
                counts["unpaid_leave_days"] += Decimal("1")
                details.append({
                    "date": iso, "type": "unpaid_leave", "deduction_days": 1,
                    "reason": leave.get("reason") or "Approved unpaid leave",
                })
                continue
            if leave_type == "paid":
                counts["paid_leave_days"] += Decimal("1")
                continue
            if leave_type == "sick":
                counts["sick_leave_days"] += Decimal("1")
                continue

        if remote_mode == "other_site":
            counts["other_site_days"] += 1
            continue

        if iso in on_duty_ids:
            counts["on_duty_days"] += 1
            continue

        counts["working_days"] += 1
        attendance = item.get("attendance") or {}
        # Today is not penalized while the work session is still running.
        # A checked-out today session, however, is complete and can be short.
        if d == today and not attendance.get("check_out"):
            continue

        net = item.get("net_work_seconds")
        if net is None or int(net or 0) < 8 * 3600:
            counts["short_8h_days"] += 1
            details.append({
                "date": iso,
                "type": "short_8h_day",
                "deduction_days": 0,
                "worked_hours": round((int(net or 0) / 3600), 2),
                "reason": "Completed/elapsed working day below 8 hours; not marked as half-day or exempt work mode.",
            })

    short_penalty = Decimal("0.5") if counts["short_8h_days"] > 3 else Decimal("0")
    deduction_days = counts["unpaid_leave_days"] + counts["unpaid_half_leave_days"] + short_penalty
    per_day = Decimal(salary) / Decimal(total_days)
    deduction_amount = _money(per_day * deduction_days)
    payable = _money(max(Decimal("0"), Decimal(salary) - deduction_amount))

    # Add a summary entry for the threshold-based half-day penalty so the
    # administrator can see exactly why it was applied.
    if short_penalty:
        details.append({
            "date": None,
            "type": "short_day_threshold_penalty",
            "deduction_days": 0.5,
            "short_8h_days": counts["short_8h_days"],
            "reason": "More than 3 working days in the month were below 8 hours; 1 unpaid half-day applied.",
        })

    payload = {
        "employee_id": employee_id,
        "salary_year": year,
        "salary_month": month,
        "base_salary": _money(Decimal(salary)),
        "total_days_in_month": total_days,
        "elapsed_days_considered": elapsed_days,
        "working_days": counts["working_days"],
        "holidays": counts["holidays"],
        "sundays": counts["sundays"],
        "other_non_working_days": counts["other_non_working_days"],
        "paid_leave_days": counts["paid_leave_days"],
        "sick_leave_days": counts["sick_leave_days"],
        "unpaid_leave_days": counts["unpaid_leave_days"],
        "unpaid_half_leave_days": counts["unpaid_half_leave_days"],
        "other_site_days": counts["other_site_days"],
        "on_duty_days": counts["on_duty_days"],
        "short_8h_days": counts["short_8h_days"],
        "short_day_penalty_days": short_penalty,
        "deduction_days": deduction_days,
        "per_day_salary": _money(per_day),
        "deduction_amount": deduction_amount,
        "payable_salary": payable,
        "details": details,
        "calculated_by": performed_by,
    }

    client = get_service_client()
    existing = _saved(employee_id, year, month)
    if existing:
        result = client.table("salary_calculations").update(payload).eq("id", existing["id"]).execute()
        row = result.data[0]
        action = "SALARY_CALCULATION_UPDATED"
        old_value = {k: existing.get(k) for k in ("base_salary", "deduction_days", "deduction_amount", "payable_salary")}
    else:
        result = client.table("salary_calculations").insert(payload).execute()
        row = result.data[0]
        action = "SALARY_CALCULATION_CREATED"
        old_value = None

    audit_service.write_audit_log(
        action=action,
        employee_id=employee_id,
        old_value=old_value,
        new_value={
            "salary_year": year,
            "salary_month": month,
            "base_salary": str(payload["base_salary"]),
            "deduction_days": str(deduction_days),
            "deduction_amount": str(deduction_amount),
            "payable_salary": str(payable),
        },
        performed_by=performed_by,
        reason="Monthly salary calculation",
    )
    return _response_from_row(row, target)


def _response_from_row(row: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(row)
    out["employee_name"] = target.get("name")
    out["employee_code"] = target.get("employee_code")
    out["role"] = target.get("role")
    out["year"] = row.get("salary_year")
    out["month"] = row.get("salary_month")
    out["salary"] = row.get("base_salary")
    return out
