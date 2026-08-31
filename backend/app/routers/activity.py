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

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.dependencies import get_current_employee
from app.services import activity_service, company_config_service, laptop_presence_service

router = APIRouter()


@router.post("/heartbeat")
async def heartbeat(employee: dict = Depends(get_current_employee)):
    """
    Called by the frontend's throttled activity heartbeat (every 30-60s
    while the browser detects mouse/keyboard/touch/scroll activity — see
    README section 34). Carries no data about what the activity was, only
    the fact that it happened.
    """
    settings = get_settings()
    return activity_service.record_heartbeat(employee["id"], settings)


@router.get("/today")
async def get_today(employee: dict = Depends(get_current_employee)):
    """Today's session activity summary for the calling employee only."""
    settings = get_settings()
    return activity_service.get_today_activity_summary(employee["id"], settings)


@router.post("/laptop-ping")
async def laptop_ping(employee: dict = Depends(get_current_employee)):
    """
    Called periodically by the web app while open on a non-phone device
    (see frontend/src/hooks/useLaptopPresence.js). Records only a "last
    seen" timestamp — no activity content, no continuous tracking beyond
    this single upserted row per employee. Phone check-in requires a
    recent ping here before it succeeds (Phase 14).
    """
    settings = get_settings()
    laptop_presence_service.ping(employee["id"], settings)
    return {"acknowledged": True}


@router.get("/laptop-presence")
async def laptop_presence_status(employee: dict = Depends(get_current_employee)):
    """Whether the calling employee's laptop currently counts as
    'connected' — used by the employee dashboard to show a status
    indicator and explain why check-in might be blocked."""
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    connected = laptop_presence_service.has_recent_presence(
        employee["id"], config.laptop_presence_freshness_minutes, settings
    )
    return {"connected": connected}
