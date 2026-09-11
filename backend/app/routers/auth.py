"""
Auth router.

Only endpoint in this phase: resolving the caller's employee profile from
their Supabase session. Missing-performance warnings (README section 27)
are layered on top of this in Phase 5 — the frontend calls this endpoint
right after login to decide role-based routing, then a separate call
checks for missing performance once that system exists.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services import audit_service
from app.services.supabase_client import get_service_client
from supabase import create_client

from app.dependencies import get_current_employee
from app.schemas.employee import EmployeeProfile

router = APIRouter()


@router.post("/profile", response_model=EmployeeProfile)
async def get_profile(employee: dict = Depends(get_current_employee)):
    """
    Resolve the authenticated user's employee profile and role.

    POST (rather than GET) is intentional: this call is the point where the
    backend can attach session-establishment side effects later — e.g.
    recording a last-login timestamp — without it looking like a cached,
    idempotent GET to any intermediary. It has no side effects yet in this
    phase.

    The frontend calls this immediately after Supabase Auth login to decide
    where to route the user (/employee/dashboard vs /admin/dashboard) and to
    know their role for showing/hiding UI — never as the source of truth for
    permissions, which is enforced independently on every other endpoint.
    """
    return employee


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)


@router.post("/password")
async def change_password(
    payload: ChangePasswordRequest,
    employee: dict = Depends(get_current_employee),
):
    """Change the password for the currently authenticated account.

    The current password is verified against Supabase Auth before the
    service-role client performs the password update. Password values are
    never logged or written to the application database.
    """
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different from the current password.")

    settings = get_settings()
    try:
        verifier = create_client(settings.supabase_url, settings.supabase_anon_key)
        verifier.auth.sign_in_with_password({
            "email": employee["email"],
            "password": payload.current_password,
        })
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.") from exc

    try:
        get_service_client().auth.admin.update_user_by_id(
            employee["auth_user_id"], {"password": payload.new_password}
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not change your password.") from exc

    audit_service.write_audit_log(
        action="PASSWORD_CHANGED",
        employee_id=employee["id"],
        performed_by=employee["id"],
    )
    return {"ok": True}
