"""
Attendance router.

Every route here requires authentication (get_current_employee). Phase
13: check-in and check-out now require a GPS location payload
(schemas.attendance.GpsCheckInRequest), verified server-side against the
configured office coordinates (see app/services/location_service.py) —
replacing the old public-IP allowlist requirement, which the company's
CGNAT/dynamic-IP network made unworkable. Identity, network-origin (now
GPS-origin), and server timestamps remain independent layers, matching
README "Security principles": never rely on just one control.
"""

from fastapi import APIRouter, Depends, Request

from app.config import get_settings
from app.dependencies import get_current_employee
from app.schemas.attendance import GpsCheckInRequest
from app.services import attendance_service, network_service

router = APIRouter()


@router.get("/today")
async def get_today(employee: dict = Depends(get_current_employee)):
    """
    Today's attendance for the calling employee, computed using the
    server's office-timezone "today" — not whatever date the employee's
    device thinks it is. Returns a placeholder shape (all fields null
    except attendance_date) if no attendance row exists yet today.
    """
    settings = get_settings()
    today = attendance_service.get_office_today(settings)
    row = attendance_service.get_attendance_for_date(employee["id"], today)
    if row:
        return row
    return {
        "attendance_date": today.isoformat(),
        "check_in": None,
        "check_out": None,
        "status": None,
    }


@router.post("/check-in")
async def check_in(
    payload: GpsCheckInRequest,
    request: Request,
    employee: dict = Depends(get_current_employee),
):
    """
    GPS-verified check-in (Phase 13). The client sends only raw GPS
    coordinates and accuracy — every other field written (employee, date,
    time, status, source, verified distance) is derived here, never
    accepted from the request body (see README "Employee ID security" and
    "No client-side security"). The resolved request IP is captured only
    as informational/audit metadata, not as an authorization gate.
    """
    settings = get_settings()
    client_ip = network_service.get_verified_client_ip(request)
    return attendance_service.create_check_in(
        employee["id"], payload.latitude, payload.longitude, payload.accuracy, settings, client_ip=client_ip
    )


@router.post("/check-out")
async def check_out(
    payload: GpsCheckInRequest,
    request: Request,
    employee: dict = Depends(get_current_employee),
):
    """GPS-verified check-out — same verification as check-in."""
    settings = get_settings()
    client_ip = network_service.get_verified_client_ip(request)
    return attendance_service.create_check_out(
        employee["id"], payload.latitude, payload.longitude, payload.accuracy, settings, client_ip=client_ip
    )


@router.get("/history")
async def get_history(employee: dict = Depends(get_current_employee)):
    """Attendance history for the calling employee."""
    settings = get_settings()
    return attendance_service.get_attendance_history(
        employee["id"],
        settings,
    )
