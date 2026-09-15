"""Monthly salary calculation for Employees and Admins.

Salary deductions are intentionally transparent and calendar-day based:
- full approved unpaid leave = 1 deduction day
- approved half-day leave = 0.5 deduction day
- every 5 missed check-in/check-out events = 0.5 deduction day (combined)
- every 3 eligible working days below the 8-hour target = 0.5 deduction day
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
        .update({"monthly_salary": float(_money(Decimal(salary)))})
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
        "short_session_full_day_days": Decimal("0"),
        "short_session_half_day_days": Decimal("0"),
        "lop_days": 0,
        "missed_check_in_days": 0,
        "missed_check_out_days": 0,
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

        # Only elapsed days can be a missed check-in/check-out event. Today
        # remains actionable and is never penalized while the day is open.
        if d < today:
            if not attendance.get("check_in"):
                counts["missed_check_in_days"] += 1
                details.append({
                    "date": iso,
                    "type": "missed_check_in",
                    "deduction_days": 0,
                    "reason": "No attendance check-in recorded for an elapsed working day.",
                })
                continue
            if not attendance.get("check_out"):
                counts["missed_check_out_days"] += 1
                details.append({
                    "date": iso,
                    "type": "missed_check_out",
                    "deduction_days": 0,
                    "reason": "Check-in exists but no check-out was recorded for an elapsed working day.",
                })
                continue

        # Today is not penalized while the work session is still running.
        # A checked-out today session, however, is complete and can be short.
        if d == today and not attendance.get("check_out"):
            continue

        net = item.get("net_work_seconds")
        if net is None:
            continue
        seconds = int(net or 0)
        hours = round(seconds / 3600, 2)
        if seconds <= 3 * 3600:
            counts["short_session_full_day_days"] += Decimal("1")
            details.append({
                "date": iso, "type": "full_day_leave_short_session", "deduction_days": 1,
                "worked_hours": hours,
                "reason": "Net worked time was 0 to 3 hours; classified as full-day leave for salary purposes.",
            })
        elif seconds <= 6 * 3600:
            counts["short_session_half_day_days"] += Decimal("0.5")
            details.append({
                "date": iso, "type": "half_day_leave_short_session", "deduction_days": 0.5,
                "worked_hours": hours,
                "reason": "Net worked time was above 3 to 6 hours; classified as half-day leave for salary purposes.",
            })
        elif seconds < 8 * 3600:
            counts["lop_days"] += 1
            counts["short_8h_days"] += 1
            details.append({
                "date": iso, "type": "lop_short_session", "deduction_days": 0,
                "worked_hours": hours,
                "reason": "Net worked time was above 6 to below 8 hours; classified as LOP. Every 4 LOP days produce 0.5 deduction day.",
            })

    missed_events = counts["missed_check_in_days"] + counts["missed_check_out_days"]
    missed_event_penalty = (Decimal(missed_events // 5) * Decimal("0.5"))
    lop_penalty = (Decimal(counts["lop_days"] // 4) * Decimal("0.5"))
    short_session_penalty = counts["short_session_full_day_days"] + counts["short_session_half_day_days"]
    deduction_days = (counts["unpaid_leave_days"] + counts["unpaid_half_leave_days"] +
                      short_session_penalty + missed_event_penalty + lop_penalty)
    per_day = Decimal(salary) / Decimal(total_days)
    deduction_amount = _money(per_day * deduction_days)
    payable = _money(max(Decimal("0"), Decimal(salary) - deduction_amount))

    # Add summary entries for threshold-based penalties so the administrator
    # can see how the reductions scale as the counts increase.
    if missed_event_penalty:
        details.append({
            "date": None,
            "type": "missed_attendance_threshold_penalty",
            "deduction_days": float(missed_event_penalty),
            "missed_check_in_days": counts["missed_check_in_days"],
            "missed_check_out_days": counts["missed_check_out_days"],
            "missed_attendance_events": missed_events,
            "reason": f"Every 5 combined missed check-in/check-out events = 0.5 deduction day; {missed_events} events produced {missed_event_penalty} deduction days.",
        })
    if lop_penalty:
        details.append({
            "date": None, "type": "lop_threshold_penalty",
            "deduction_days": float(lop_penalty), "lop_days": counts["lop_days"],
            "reason": f"Every 4 LOP days (6 to below 8 hours) = 0.5 deduction day; {counts['lop_days']} LOP days produced {lop_penalty} deduction days.",
        })

    payload = {
        "employee_id": employee_id,
        "salary_year": year,
        "salary_month": month,
        "base_salary": float(_money(Decimal(salary))),
        "total_days_in_month": total_days,
        "elapsed_days_considered": elapsed_days,
        "working_days": counts["working_days"],
        "holidays": counts["holidays"],
        "sundays": counts["sundays"],
        "other_non_working_days": counts["other_non_working_days"],
        "paid_leave_days": float(counts["paid_leave_days"]),
        "sick_leave_days": float(counts["sick_leave_days"]),
        "unpaid_leave_days": float(counts["unpaid_leave_days"]),
        "unpaid_half_leave_days": float(counts["unpaid_half_leave_days"]),
        "other_site_days": counts["other_site_days"],
        "on_duty_days": counts["on_duty_days"],
        "short_8h_days": counts["short_8h_days"],
        "short_session_full_day_days": float(counts["short_session_full_day_days"]),
        "short_session_half_day_days": float(counts["short_session_half_day_days"]),
        "lop_days": counts["lop_days"],
        "missed_check_in_days": counts["missed_check_in_days"],
        "missed_check_out_days": counts["missed_check_out_days"],
        "missed_attendance_events": missed_events,
        "missed_event_penalty_days": float(missed_event_penalty),
        "short_day_penalty_days": float(lop_penalty),
        "deduction_days": float(deduction_days),
        "per_day_salary": float(_money(per_day)),
        "deduction_amount": float(deduction_amount),
        "payable_salary": float(payable),
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
