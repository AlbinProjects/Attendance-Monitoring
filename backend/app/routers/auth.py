"""
Auth router.

Only endpoint in this phase: resolving the caller's employee profile from
their Supabase session. Missing-performance warnings (README section 27)
are layered on top of this in Phase 5 — the frontend calls this endpoint
right after login to decide role-based routing, then a separate call
checks for missing performance once that system exists.
"""

from fastapi import APIRouter, Depends

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
