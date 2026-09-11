"""Short-lived authorization for the privacy-scoped desktop activity agent."""
from datetime import timedelta
from jose import jwt

from app.config import Settings
from app.services.time_service import get_office_now

AGENT_TOKEN_MINUTES = 15


def _secret(settings: Settings) -> str:
    return settings.activity_agent_secret or settings.supabase_service_role_key


def issue_agent_token(employee_id: str, settings: Settings) -> dict:
    now = get_office_now(settings)
    exp = now + timedelta(minutes=AGENT_TOKEN_MINUTES)
    payload = {
        "sub": employee_id,
        "typ": "activity_agent",
        "aud": "activity-agent",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, _secret(settings), algorithm="HS256")
    return {
        "token": token,
        "expires_in": AGENT_TOKEN_MINUTES * 60,
        "server_time": now.isoformat(),
    }
