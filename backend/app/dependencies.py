"""
Shared FastAPI dependencies.

- get_current_employee(): verifies the Supabase JWT from the Authorization
  header, loads the matching row from `employees` using the service-role
  client (bypassing RLS — we don't know who the caller is yet), and rejects
  unknown or inactive accounts. This is the ONLY source of truth for "who is
  making this request" anywhere in the backend — request bodies are never
  trusted for identity, ever. See README "Employee ID security".
- require_role(*roles): dependency factory that raises 403 unless the
  current employee's role is in `roles`.

Network/IP verification (app/services/network_service.py) is no longer an
attendance authorization gate as of Phase 13 — see
app/services/location_service.py for GPS-based attendance verification,
which routers/attendance.py calls directly via attendance_service.
"""

from typing import Any, Dict

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import get_settings
from app.services.supabase_client import get_service_client

bearer_scheme = HTTPBearer(auto_error=True)

Employee = Dict[str, Any]


def _decode_supabase_jwt(token: str) -> dict:
    """
    Verify a Supabase Auth access token's signature and standard claims
    (expiry, audience) using the project's JWT secret. Supabase issues
    HS256-signed tokens with audience "authenticated" for logged-in users.
    """
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in to continue.",
        ) from exc


async def get_current_employee(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> Employee:
    """
    Resolve the authenticated employee from the bearer token. This is the
    dependency every protected route uses to find out "who is calling" —
    nothing else (query params, body fields, headers set by the client) is
    ever trusted for identity.
    """
    payload = _decode_supabase_jwt(credentials.credentials)
    auth_user_id = payload.get("sub")
    if not auth_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in to continue.",
        )

    client = get_service_client()
    result = (
        client.table("employees")
        .select("*")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    employee = result.data

    if not employee:
        # A valid Supabase Auth user with no matching employees row — e.g.
        # an account created in Supabase Auth but never provisioned as an
        # employee. Treat as forbidden, not "not found", to avoid leaking
        # whether the auth account itself exists.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No employee profile found for this account. Contact an administrator.",
        )

    if not employee["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is inactive. Contact an administrator.",
        )

    return employee


def require_role(*allowed_roles: str):
    """
    Dependency factory for role-gated routes.

        @router.get("/admin/dashboard")
        async def admin_dashboard(employee = Depends(require_role("admin", "super_admin"))):
            ...

    A regular employee calling this route — including by hand-crafting the
    request, e.g. `curl` against /api/admin/...  — always receives 403,
    regardless of what the frontend does or doesn't render.
    """

    async def _check_role(employee: Employee = Depends(get_current_employee)) -> Employee:
        if employee["role"] not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return employee

    return _check_role
