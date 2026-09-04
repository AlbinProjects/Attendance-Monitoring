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
from app.services import jwks_service
from app.services.supabase_client import get_service_client

bearer_scheme = HTTPBearer(auto_error=True)

Employee = Dict[str, Any]


def _decode_supabase_jwt(token: str) -> dict:
    """
    Verify a Supabase Auth access token's signature and standard claims
    (expiry, audience). Supabase projects can be on one of two systems:

    - Legacy: a single shared HS256 secret (SUPABASE_JWT_SECRET) signs
      and verifies every token.
    - Newer "JWT Signing Keys": tokens are signed asymmetrically
      (typically ES256) with a private key only Supabase holds;
      verification uses the corresponding PUBLIC key, fetched from the
      project's JWKS endpoint (app/services/jwks_service.py) and matched
      by the token's `kid` (key ID) header.

    We support both so this backend works regardless of which system a
    given Supabase project is on — this is determined by reading the
    token's own header (`alg`), not by any app configuration, so nothing
    needs to change here if a project migrates between the two later.
    """
    settings = get_settings()

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in to continue.",
        ) from exc

    alg = unverified_header.get("alg")
    kid = unverified_header.get("kid")

    if alg and alg != "HS256":
        return _decode_via_jwks(token, alg, kid, settings)

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


def _decode_via_jwks(token: str, alg: str, kid: str, settings) -> dict:
    try:
        keys = jwks_service.get_jwks(settings.supabase_url)
        key = jwks_service.find_key_for_kid(keys, kid)
        if not key:
            # The kid we need might be missing because Supabase rotated
            # keys since our last fetch — refetch once before giving up,
            # rather than caching a permanent failure until the TTL expires.
            jwks_service.clear_cache()
            keys = jwks_service.get_jwks(settings.supabase_url)
            key = jwks_service.find_key_for_kid(keys, kid)
        if not key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Please log in to continue.",
            )
        return jwt.decode(token, key, algorithms=[alg], audience="authenticated")
    except HTTPException:
        raise
    except Exception as exc:
        # Covers both JWT verification failures (JWTError) and JWKS fetch
        # failures (network error, non-2xx response, malformed JSON) —
        # all of these should look identical to the client: a 401, never
        # a 500. A JWKS outage is a backend operational problem, not
        # something the client did wrong, but "please log in again" is
        # still the safest generic response to show them.
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
