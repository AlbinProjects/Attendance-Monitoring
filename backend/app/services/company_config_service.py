"""
Effective company configuration (Phase 14).

Company-wide attendance settings — network mode (static/dynamic),
office GPS location, and how fresh a laptop presence ping must be — can
now be edited at runtime by a Super Admin (see routers/company_settings.py
and frontend/src/pages/admin/CompanySettings.jsx), not just set once via
env vars at deploy time. This module is the single place that resolves
"what's the value right now": the `company_settings` DB row takes
precedence when a value is set there; any NULL/unset DB value falls back
to the corresponding env var default (`app/config.py`). On any DB error,
everything falls back to env vars rather than blocking all attendance
company-wide over a transient Supabase outage — matching the same
fail-safe behavior established for `allowed_ips` in Phase 4.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.config import Settings
from app.services import audit_service
from app.services.supabase_client import get_service_client


@dataclass
class EffectiveConfig:
    network_mode: str  # "static" | "dynamic"
    allowed_ips: List[str]
    office_latitude: float
    office_longitude: float
    office_gps_radius_meters: float
    max_gps_accuracy_meters: float
    laptop_presence_freshness_minutes: int


def _get_company_settings_row() -> Optional[Dict[str, Any]]:
    try:
        client = get_service_client()
        result = client.table("company_settings").select("*").eq("id", 1).maybe_single().execute()
        return result.data
    except Exception:
        return None


def get_effective_config(settings: Settings) -> EffectiveConfig:
    row = _get_company_settings_row() or {}

    return EffectiveConfig(
        network_mode=row.get("network_mode") or "dynamic",
        allowed_ips=row.get("allowed_ips") or settings.company_allowed_ips,
        office_latitude=(
            row["office_latitude"] if row.get("office_latitude") is not None else settings.office_latitude
        ),
        office_longitude=(
            row["office_longitude"] if row.get("office_longitude") is not None else settings.office_longitude
        ),
        office_gps_radius_meters=(
            row["office_gps_radius_meters"]
            if row.get("office_gps_radius_meters") is not None
            else settings.office_gps_radius_meters
        ),
        max_gps_accuracy_meters=(
            row["max_gps_accuracy_meters"]
            if row.get("max_gps_accuracy_meters") is not None
            else settings.max_gps_accuracy_meters
        ),
        laptop_presence_freshness_minutes=(
            row.get("laptop_presence_freshness_minutes")
            if row.get("laptop_presence_freshness_minutes") is not None
            else 5
        ),
    )


def get_raw_company_settings() -> Dict[str, Any]:
    """Full company_settings row for the admin settings page — includes
    every field (performance/inactivity thresholds too), not just the
    attendance-verification subset EffectiveConfig covers."""
    row = _get_company_settings_row()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Company settings could not be loaded.",
        )
    return row


def update_company_settings(
    payload: Dict[str, Any],
    performed_by_employee_id: str,
    ip_address: Optional[str],
) -> Dict[str, Any]:
    """Super-Admin-only (enforced by the router). Only fields actually
    present in payload are changed; everything else keeps its current
    value. Always audited."""
    existing = get_raw_company_settings()

    update_fields = {k: v for k, v in payload.items() if v is not None}
    if not update_fields:
        return existing

    client = get_service_client()
    result = client.table("company_settings").update(update_fields).eq("id", 1).execute()
    row = result.data[0]

    audit_service.write_audit_log(
        action="COMPANY_SETTINGS_UPDATED",
        old_value={k: existing.get(k) for k in update_fields},
        new_value=update_fields,
        performed_by=performed_by_employee_id,
        ip_address=ip_address,
    )
    return row
