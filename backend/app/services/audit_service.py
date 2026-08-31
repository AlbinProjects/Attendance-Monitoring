"""
Audit logging service.

Every write here goes through the service-role Supabase client, which is
the ONLY way an audit_logs row can ever be created — RLS grants no
INSERT policy to any authenticated role, including admins (see
supabase/migrations/003_rls_policies.sql). That means an audit trail
written through this module cannot be forged or bypassed by a client
calling Supabase directly, even with valid admin credentials.

Callers should treat write_audit_log as fire-and-forget from the request's
perspective — a failure here should be logged but should NOT be allowed to
silently roll back or hide the underlying action it's recording, since that
would leave real state changes with no audit trail. Currently we let
exceptions propagate so the caller decides; attendance_service in this
phase writes the audit row after the underlying insert/update succeeds and
does not catch failures here, which is a known area to revisit with
retries/queuing in a production hardening pass (see README "Known
limitations").
"""

from typing import Any, Dict, List, Optional

from app.services.supabase_client import get_service_client

VALID_ACTIONS = {
    "CHECK_IN",
    "CHECK_OUT",
    "ADMIN_ATTENDANCE_CREATED",
    "ADMIN_ATTENDANCE_UPDATED",
    "ADMIN_ATTENDANCE_DELETED",
    "EMPLOYEE_CREATED",
    "EMPLOYEE_UPDATED",
    "EMPLOYEE_ROLE_CHANGED",
    "EMPLOYEE_DISABLED",
    "COMPANY_SETTINGS_UPDATED",
}


def write_audit_log(
    action: str,
    *,
    employee_id: Optional[str] = None,
    attendance_id: Optional[str] = None,
    old_value: Optional[Dict[str, Any]] = None,
    new_value: Optional[Dict[str, Any]] = None,
    performed_by: Optional[str] = None,
    reason: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    if action not in VALID_ACTIONS:
        raise ValueError(f"Unknown audit action: {action!r}")

    client = get_service_client()
    client.table("audit_logs").insert(
        {
            "action": action,
            "employee_id": employee_id,
            "attendance_id": attendance_id,
            "old_value": old_value,
            "new_value": new_value,
            "performed_by": performed_by,
            "reason": reason,
            "ip_address": ip_address,
        }
    ).execute()


def get_audit_logs(
    *,
    employee_id: Optional[str] = None,
    attendance_id: Optional[str] = None,
    action: Optional[str] = None,
    performed_by: Optional[str] = None,
    on_date: Optional[str] = None,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """
    Read-only query for the admin audit viewer. Note there is deliberately
    no delete_audit_log function anywhere in this codebase — audit rows
    are permanent once written, matching README "Do not provide normal
    deletion of audit records."
    """
    client = get_service_client()
    query = client.table("audit_logs").select("*")
    if employee_id:
        query = query.eq("employee_id", employee_id)
    if attendance_id:
        query = query.eq("attendance_id", attendance_id)
    if action:
        query = query.eq("action", action)
    if performed_by:
        query = query.eq("performed_by", performed_by)
    rows = query.execute().data or []

    if on_date:
        rows = [r for r in rows if (r.get("created_at") or "").startswith(on_date)]

    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:limit]
