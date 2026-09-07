"""Pydantic schemas for employee data."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

Role = Literal["employee", "admin", "super_admin"]


class EmployeeProfile(BaseModel):
    """
    What we return to the frontend after authentication. Deliberately
    excludes auth_user_id (internal linkage detail, no reason to expose it)
    and anything not needed for the client to render the UI and route the
    user to the right dashboard.
    """

    id: str
    employee_code: str
    name: str
    email: str
    department: Optional[str] = None
    designation: Optional[str] = None
    role: Role
    joining_date: Optional[date] = None
    is_active: bool
