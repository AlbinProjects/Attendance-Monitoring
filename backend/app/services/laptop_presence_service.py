"""
Laptop presence service (Phase 14).

Tracks a single "last seen" timestamp per employee, upserted by a
periodic ping from the web app while it's open on a non-phone device (see
frontend/src/hooks/useLaptopPresence.js). This is deliberately NOT tied to
an attendance_id — it has to exist BEFORE check-in, since check-in is the
thing that creates the attendance record, and check-in is gated on a
recent presence row existing (see attendance_service.create_check_in).

This is a presence signal, not an activity/productivity measure — it only
records "the app was open on a laptop recently," nothing about what the
employee did on that laptop. Activity/inactivity monitoring (Phase 6,
activity_service.py) is a separate, already-privacy-scoped system that
this does not change or duplicate.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.config import Settings
from app.services.supabase_client import get_service_client
from app.services.time_service import get_office_now


def ping(employee_id: str, settings: Settings) -> None:
    now = get_office_now(settings)
    client = get_service_client()
    existing = get_presence(employee_id)
    payload = {"employee_id": employee_id, "last_seen_at": now.isoformat()}
    if existing:
        client.table("laptop_presence").update(payload).eq("employee_id", employee_id).execute()
    else:
        client.table("laptop_presence").insert(payload).execute()


def get_presence(employee_id: str) -> Optional[Dict[str, Any]]:
    client = get_service_client()
    result = (
        client.table("laptop_presence")
        .select("*")
        .eq("employee_id", employee_id)
        .maybe_single()
        .execute()
    )
    return result.data


def has_recent_presence(employee_id: str, freshness_minutes: int, settings: Settings) -> bool:
    """True if the employee's laptop pinged within the last
    `freshness_minutes`. False if it never pinged at all, or the most
    recent ping is stale."""
    row = get_presence(employee_id)
    if not row:
        return False
    last_seen = datetime.fromisoformat(row["last_seen_at"])
    now = get_office_now(settings)
    return (now - last_seen) <= timedelta(minutes=freshness_minutes)
