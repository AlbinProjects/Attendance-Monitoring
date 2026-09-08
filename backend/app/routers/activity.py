"""
Activity router.

Labeled "System Activity Monitoring" everywhere in this codebase and the
UI copy it powers — never "Productivity Monitoring". See README "Privacy
requirements" and "Important limitation of browser activity" for what this
feature does and does not measure.

Phase 14: also hosts the laptop presence ping/status endpoints — a
separate, simpler signal ("is the app open on a laptop right now") that
phone check-in depends on, independent of activity/inactivity monitoring.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies import get_current_activity_agent, get_current_employee, require_role
from app.services import activity_service, company_config_service, laptop_presence_service, remote_work_service, on_duty_service, desktop_agent_service

router = APIRouter()


@router.post("/heartbeat")
async def heartbeat(employee: dict = Depends(require_role("employee"))):
    """
    Called by the frontend's throttled activity heartbeat (every 30-60s
    while the browser detects mouse/keyboard/touch/scroll activity — see
    README section 34). Carries no data about what the activity was, only
    the fact that it happened.
    """
    settings = get_settings()
    return activity_service.record_heartbeat(employee["id"], settings)


@router.get("/monitoring-config")
async def monitoring_config(employee: dict = Depends(require_role("employee"))):
    """Return the company desktop-monitoring mode for the employee UI.

    This is intentionally read-only for employees; only Super Admin can
    change the company setting through /admin/settings.
    """
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    return {"advanced_desktop_monitoring_enabled": config.advanced_desktop_monitoring_enabled}


@router.post("/agent-token")
async def agent_token(employee: dict = Depends(require_role("employee"))):
    """Issue a 3-minute desktop-agent token for an open attendance session.

    The browser is already authenticated with Supabase. The local agent gets
    only this short-lived, employee-scoped token; it never receives the
    employee's Supabase session or any application data.
    """
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    if not config.advanced_desktop_monitoring_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Advanced desktop monitoring is disabled by the company.")
    attendance = activity_service.attendance_service.get_attendance_for_date(
        employee["id"], activity_service.get_office_today(settings)
    )
    remote = remote_work_service.get_today(employee["id"])
    on_duty = on_duty_service.get_today(employee["id"])
    if (remote and remote.get("work_mode") == "other_site") or on_duty:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Desktop activity monitoring is not used for this work mode.")
    if not attendance or not attendance.get("check_in") or attendance.get("check_out"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You must have an open attendance session before connecting the desktop activity agent.")
    return desktop_agent_service.issue_agent_token(employee["id"], settings)


@router.post("/agent-ping")
async def agent_ping(employee: dict = Depends(get_current_activity_agent)):
    """Validate a live desktop-agent session without recording work activity."""
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    if not config.advanced_desktop_monitoring_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Advanced desktop monitoring is disabled by the company.")
    remote = remote_work_service.get_today(employee["id"])
    on_duty = on_duty_service.get_today(employee["id"])
    if (remote and remote.get("work_mode") == "other_site") or on_duty:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Desktop activity monitoring is not used for this work mode.")
    return {"authorized": True}


@router.post("/desktop-heartbeat")
async def desktop_heartbeat(employee: dict = Depends(get_current_activity_agent)):
    """Record a privacy-preserving activity signal from the local agent."""
    settings = get_settings()
    return activity_service.record_heartbeat(employee["id"], settings)


@router.post("/desktop-event")
async def desktop_event(payload: dict, employee: dict = Depends(get_current_activity_agent)):
    """Ingest a timestamped desktop-agent event. Only coarse activity state
    and monitoring connectivity intervals are accepted; no content is stored."""
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    if not config.advanced_desktop_monitoring_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Advanced desktop monitoring is disabled by the company.")
    remote = remote_work_service.get_today(employee["id"])
    on_duty = on_duty_service.get_today(employee["id"])
    if (remote and remote.get("work_mode") == "other_site") or on_duty:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Desktop activity monitoring is not used for this work mode.")
    return activity_service.record_desktop_event(employee["id"], payload, settings)


@router.get("/today")
async def get_today(employee: dict = Depends(require_role("employee"))):
    """Today's session activity summary for the calling employee only."""
    settings = get_settings()
    return activity_service.get_today_activity_summary(employee["id"], settings)


@router.post("/laptop-ping")
async def laptop_ping(employee: dict = Depends(require_role("employee"))):
    """
    Called periodically by the web app while open on a non-phone device
    (see frontend/src/hooks/useLaptopPresence.js). Records only a "last
    seen" timestamp — no activity content, no continuous tracking beyond
    this single upserted row per employee. Phone check-in requires a
    recent ping here before it succeeds (Phase 14).
    """
    settings = get_settings()
    # Other Site and On Duty intentionally do not require or collect laptop
    # presence. Keep the endpoint harmless for clients that still have the
    # layout mounted. Work From Home continues to require laptop presence.
    from app.services import remote_work_service, on_duty_service
    remote = remote_work_service.get_today(employee["id"])
    on_duty = on_duty_service.get_today(employee["id"])
    if (remote and remote.get("work_mode") == "other_site") or on_duty:
        return {"acknowledged": True, "required": False}
    laptop_presence_service.ping(employee["id"], settings)
    return {"acknowledged": True, "required": True}


@router.get("/laptop-presence")
async def laptop_presence_status(employee: dict = Depends(require_role("employee"))):
    """Whether the calling employee's laptop currently counts as
    'connected' — used by the employee dashboard to show a status
    indicator and explain why check-in might be blocked."""
    settings = get_settings()
    from app.services import remote_work_service, on_duty_service
    remote = remote_work_service.get_today(employee["id"])
    on_duty = on_duty_service.get_today(employee["id"])
    if (remote and remote.get("work_mode") == "other_site") or on_duty:
        return {"connected": False, "required": False}
    config = company_config_service.get_effective_config(settings)
    connected = laptop_presence_service.has_recent_presence(
        employee["id"], config.laptop_presence_freshness_minutes, settings
    )
    return {"connected": connected, "required": True}
