"""
Employees router.

List is available to admin and super_admin (view-only for admin per
README section 11). Create and update are super_admin only (README
section 12) — enforced by require_role, independent of anything the
frontend hides.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Request

from app.dependencies import require_role
from app.schemas.admin import EmployeeCreateRequest, EmployeeUpdateRequest
from app.services import employees_service, network_service

router = APIRouter()


def _public_view(row: Dict[str, Any]) -> Dict[str, Any]:
    """Strips auth_user_id — an internal Supabase Auth linkage detail with
    no frontend use — before a row ever leaves this router. Response
    minimization: even though access here is already properly
    authorized, there's no reason to hand out an internal ID the client
    never needs."""
    return {k: v for k, v in row.items() if k != "auth_user_id"}


@router.get("")
async def list_employees(
    _employee: dict = Depends(require_role("admin", "super_admin")),
    search: Optional[str] = None,
    department: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
):
    rows = employees_service.list_employees(
        search=search, department=department, role=role, is_active=is_active
    )
    return [_public_view(r) for r in rows]


@router.post("")
async def create_employee(
    payload: EmployeeCreateRequest,
    request: Request,
    employee: dict = Depends(require_role("super_admin")),
):
    ip_address = network_service.get_verified_client_ip(request)
    row, temp_password = employees_service.create_employee(
        payload.model_dump(), employee["id"], ip_address
    )
    # Surfaced exactly once for the Super Admin to relay to the new
    # employee out-of-band — never logged or stored anywhere.
    return {**_public_view(row), "temporary_password": temp_password}


@router.put("/{employee_id}")
async def update_employee(
    employee_id: str,
    payload: EmployeeUpdateRequest,
    request: Request,
    employee: dict = Depends(require_role("super_admin")),
):
    ip_address = network_service.get_verified_client_ip(request)
    row = employees_service.update_employee(
        employee_id, payload.model_dump(exclude_unset=True), employee["id"], ip_address
    )
    return _public_view(row)
