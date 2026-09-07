"""
Employee management service.

Creating an employee means creating a REAL Supabase Auth user (via the
admin API, which requires the service-role key — never callable from the
frontend) and then inserting the corresponding `employees` row. Every
write here that changes role or active status is audited (see README
section 12 — these are exclusively Super Admin capabilities, enforced by
require_role("super_admin") at the router level, not here).
"""

import secrets
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status

from app.services import audit_service
from app.services.supabase_client import get_service_client

# ~100 years — effectively permanent until explicitly re-enabled. Supabase
# requires a duration string rather than "forever", so this is the
# practical equivalent.
BAN_DURATION_PERMANENT = "876000h"
BAN_DURATION_NONE = "none"


def _serialize(value):
    return value.isoformat() if isinstance(value, date) else value


def list_employees(
    *,
    search: Optional[str] = None,
    department: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    client = get_service_client()
    query = client.table("employees").select("*")
    if department:
        query = query.eq("department", department)
    if role:
        query = query.eq("role", role)
    if is_active is not None:
        query = query.eq("is_active", is_active)
    rows = query.execute().data or []

    if search:
        needle = search.lower()
        rows = [
            r
            for r in rows
            if needle in (r.get("name") or "").lower()
            or needle in (r.get("email") or "").lower()
            or needle in (r.get("employee_code") or "").lower()
        ]

    rows.sort(key=lambda r: r.get("name") or "")
    return rows


def create_employee(
    payload: Dict[str, Any],
    created_by_employee_id: str,
    ip_address: Optional[str],
) -> Tuple[Dict[str, Any], str]:
    """
    Provisions a real login (Supabase Auth user) plus the employees row.
    Returns (employee_row, temporary_password) — the password is surfaced
    exactly once in the API response for the Super Admin to hand to the
    new employee out-of-band; it is never logged or stored anywhere by
    this backend.

    Known limitation: if the employees-table insert fails after the auth
    user was already created (e.g. a duplicate employee_code), the orphaned
    Supabase Auth user is not automatically cleaned up — this is flagged
    for a future hardening pass rather than silently retried, since
    automatic cleanup of auth accounts carries its own risk of deleting the
    wrong thing under a race.
    """
    client = get_service_client()
    temp_password = payload.get("password") or secrets.token_urlsafe(12)

    try:
        auth_result = client.auth.admin.create_user(
            {
                "email": payload["email"],
                "password": temp_password,
                "email_confirm": True,
            }
        )
    except Exception as exc:
        # Deliberately generic: never return raw exception internals to an
        # API client, even an authenticated super_admin one — the
        # underlying error (e.g. Supabase connectivity, malformed email)
        # belongs in server-side logs, not the HTTP response body.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create the login account. The email address may already be in use, "
            "or the identity provider is temporarily unavailable.",
        ) from exc

    auth_user_id = auth_result.user.id

    employee_row = {
        "auth_user_id": auth_user_id,
        "employee_code": payload["employee_code"],
        "name": payload["name"],
        "email": payload["email"],
        "department": payload.get("department"),
        "designation": payload.get("designation"),
        "role": payload.get("role") or "employee",
        "joining_date": _serialize(payload.get("joining_date")),
        "is_active": True,
    }

    try:
        result = client.table("employees").insert(employee_row).execute()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An employee with this code or email may already exist.",
        ) from exc

    row = result.data[0]
    audit_service.write_audit_log(
        action="EMPLOYEE_CREATED",
        employee_id=row["id"],
        new_value={"role": row["role"], "email": row["email"]},
        performed_by=created_by_employee_id,
        ip_address=ip_address,
    )
    return row, temp_password


def update_employee(
    employee_id: str,
    payload: Dict[str, Any],
    performed_by: str,
    ip_address: Optional[str],
) -> Dict[str, Any]:
    """
    Handles profile edits, role changes, and enabling/disabling — each
    audited distinctly so the trail reads clearly (a role change is not
    logged the same generic way as fixing a typo in a department name).
    """
    client = get_service_client()
    existing = client.table("employees").select("*").eq("id", employee_id).maybe_single().execute().data
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    update_fields: Dict[str, Any] = {}
    for field in ("employee_code", "name", "email", "department", "designation", "joining_date"):
        if field in payload and payload[field] is not None:
            update_fields[field] = _serialize(payload[field])

    identity_changed = any(field in update_fields for field in ("employee_code", "email"))
    old_email = existing.get("email")
    new_email = update_fields.get("email")

    role_changed = (
        "role" in payload and payload["role"] is not None and payload["role"] != existing["role"]
    )
    if role_changed:
        update_fields["role"] = payload["role"]

    disabling = payload.get("is_active") is False and existing["is_active"] is True
    enabling = payload.get("is_active") is True and existing["is_active"] is False
    if "is_active" in payload and payload["is_active"] is not None:
        update_fields["is_active"] = payload["is_active"]

    if not update_fields:
        return existing

    # Keep Supabase Auth email and the application employee email in sync.
    # This operation is only reachable by Super Admin for email changes.
    if new_email is not None and new_email != old_email:
        try:
            client.auth.admin.update_user_by_id(
                existing["auth_user_id"],
                {"email": new_email, "email_confirm": True},
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Could not update the login email. The new email may already be in use.",
            ) from exc

    try:
        result = client.table("employees").update(update_fields).eq("id", employee_id).execute()
        row = result.data[0]
    except Exception as exc:
        # Best-effort rollback of Auth email if the application-row update
        # fails after Auth was changed.
        if new_email is not None and new_email != old_email:
            try:
                client.auth.admin.update_user_by_id(
                    existing["auth_user_id"],
                    {"email": old_email, "email_confirm": True},
                )
            except Exception:
                pass
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not update the employee. The employee ID or email may already be in use.",
        ) from exc

    if role_changed:
        audit_service.write_audit_log(
            action="EMPLOYEE_ROLE_CHANGED",
            employee_id=employee_id,
            old_value={"role": existing["role"]},
            new_value={"role": row["role"]},
            performed_by=performed_by,
            ip_address=ip_address,
        )

    if disabling:
        audit_service.write_audit_log(
            action="EMPLOYEE_DISABLED",
            employee_id=employee_id,
            old_value={"is_active": True},
            new_value={"is_active": False},
            performed_by=performed_by,
            ip_address=ip_address,
        )
        # Defense-in-depth: also ban the Supabase Auth account itself so a
        # disabled employee can't obtain a fresh session token, not just
        # rely on the is_active check in get_current_employee. That check
        # remains authoritative regardless of whether this call succeeds.
        try:
            client.auth.admin.update_user_by_id(
                existing["auth_user_id"], {"ban_duration": BAN_DURATION_PERMANENT}
            )
        except Exception:
            pass

    if enabling:
        try:
            client.auth.admin.update_user_by_id(
                existing["auth_user_id"], {"ban_duration": BAN_DURATION_NONE}
            )
        except Exception:
            pass

    other_fields_changed = bool(set(update_fields) - {"role", "is_active"})
    if other_fields_changed and not role_changed and not disabling and not enabling:
        audit_service.write_audit_log(
            action="EMPLOYEE_UPDATED",
            employee_id=employee_id,
            old_value={
                field: existing.get(field)
                for field in update_fields
            },
            new_value=update_fields,
            performed_by=performed_by,
            ip_address=ip_address,
        )

    if identity_changed:
        audit_service.write_audit_log(
            action="EMPLOYEE_ID_OR_EMAIL_CHANGED",
            employee_id=employee_id,
            old_value={
                "employee_code": existing.get("employee_code"),
                "email": existing.get("email"),
            },
            new_value={
                "employee_code": row.get("employee_code"),
                "email": row.get("email"),
            },
            performed_by=performed_by,
            ip_address=ip_address,
        )

    return row


def delete_employee(
    employee_id: str,
    performed_by: str,
    ip_address: Optional[str],
) -> None:
    """Permanently delete an employee/admin account.

    Only the router exposes this operation to Super Admin. A Super Admin
    target is explicitly protected. Because historical tables use RESTRICT
    foreign keys, linked operational records are removed first; audit logs
    retain the deletion event with performed_by/employee references nulled
    by their existing ON DELETE SET NULL relationships.
    """
    client = get_service_client()
    existing = (
        client.table("employees")
        .select("*")
        .eq("id", employee_id)
        .maybe_single()
        .execute()
        .data
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found.")

    if existing.get("role") == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super Admin profiles cannot be deleted.",
        )

    if employee_id == performed_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot delete your own account.",
        )

    # Capture the deletion event before removing the employee row. The
    # audit_logs.employee_id FK is ON DELETE SET NULL, so the event remains.
    audit_service.write_audit_log(
        action="EMPLOYEE_DELETED",
        employee_id=employee_id,
        old_value={
            "employee_code": existing.get("employee_code"),
            "name": existing.get("name"),
            "email": existing.get("email"),
            "role": existing.get("role"),
        },
        performed_by=performed_by,
        ip_address=ip_address,
    )

    # These operational rows reference employees with ON DELETE RESTRICT.
    # Delete dependent records explicitly so a requested permanent account
    # deletion does not fail because of historical attendance/performance.
    attendance_rows = (
        client.table("attendance")
        .select("id")
        .eq("employee_id", employee_id)
        .execute()
        .data
        or []
    )
    attendance_ids = [r["id"] for r in attendance_rows]

    if attendance_ids:
        # activity_sessions / heartbeats reference attendance and employee.
        client.table("activity_sessions").delete().in_("attendance_id", attendance_ids).execute()
        client.table("activity_heartbeats").delete().in_("attendance_id", attendance_ids).execute()
        client.table("attendance").delete().in_("id", attendance_ids).execute()

    client.table("performance_updates").delete().eq("employee_id", employee_id).execute()

    # Preserve company calendar and leave history while releasing the
    # deleted user's foreign-key ownership/approval references.
    client.table("employee_leaves").update({"granted_by": None}).eq("granted_by", employee_id).execute()
    client.table("company_calendar").update({"created_by": None}).eq("created_by", employee_id).execute()
    client.table("company_calendar").update({"updated_by": None}).eq("updated_by", employee_id).execute()
    client.table("employee_leaves").delete().eq("employee_id", employee_id).execute()
    client.table("laptop_presence").delete().eq("employee_id", employee_id).execute()

    # Remove the application row before Auth because employees.auth_user_id
    # references auth.users with ON DELETE RESTRICT.
    client.table("employees").delete().eq("id", employee_id).execute()

    try:
        client.auth.admin.delete_user(existing["auth_user_id"])
    except Exception as exc:
        # The application row is already gone. Surface a clear server error
        # rather than pretending the Auth account was deleted too.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Employee data was deleted, but the login account could not be removed. Contact the system administrator.",
        ) from exc
