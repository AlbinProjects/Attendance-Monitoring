"""Pydantic schemas for attendance data."""

from datetime import date, datetime, time
from typing import Literal, Optional

from pydantic import BaseModel, Field

AttendanceStatus = Literal["present", "late", "absent", "half_day", "manual"]
AttendanceSource = Literal["wifi", "admin", "gps"]


class AttendanceRecord(BaseModel):
    id: str
    employee_id: str
    attendance_date: date
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    status: Optional[AttendanceStatus] = None
    check_in_source: Optional[AttendanceSource] = None
    check_out_source: Optional[AttendanceSource] = None
    marked_by: Optional[str] = None
    reason: Optional[str] = None
    # GPS verification metadata (Phase 13) — populated when
    # check_in_source/check_out_source == "gps", null otherwise (e.g. for
    # historical wifi-sourced rows or admin-marked attendance).
    check_in_latitude: Optional[float] = None
    check_in_longitude: Optional[float] = None
    check_in_accuracy_meters: Optional[float] = None
    check_in_distance_meters: Optional[float] = None
    check_out_latitude: Optional[float] = None
    check_out_longitude: Optional[float] = None
    check_out_accuracy_meters: Optional[float] = None
    check_out_distance_meters: Optional[float] = None


class TodayAttendance(BaseModel):
    """Distinct from AttendanceRecord: attendance_date is always present
    (today, computed server-side) even if no row exists yet — the frontend
    uses this to render "not checked in yet" without a null date."""

    attendance_date: date
    check_in: Optional[datetime] = None
    check_out: Optional[datetime] = None
    status: Optional[AttendanceStatus] = None


class GpsCheckInRequest(BaseModel):
    """
    Body for POST /api/attendance/check-in and /check-out (Phase 13).
    latitude/longitude/accuracy are the ONLY fields accepted — deliberately
    no employee_id, timestamp, status, or verification-result field exists
    here, so there is nothing for a client to inject even if they tried
    (Pydantic silently drops unknown extra fields by default). Range
    validation happens here; the actual verification decision (distance,
    accuracy threshold) is computed server-side in location_service, never
    trusted from the client.
    """

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float = Field(ge=0)


class ManualAttendanceCreateRequest(BaseModel):
    """
    Admin-only exceptional attendance creation. check_in_time/check_out_time
    are plain times-of-day (no timezone) — the backend always combines
    them with attendance_date in the configured office timezone, so there
    is no ambiguity about which timezone the admin meant. Manual attendance
    is NOT gated by GPS — it is an exceptional administrative action,
    always audited with a mandatory reason (see README section 23).
    """

    employee_id: str
    attendance_date: date
    check_in_time: Optional[time] = None
    check_out_time: Optional[time] = None
    reason: str


class AttendanceCorrectionRequest(BaseModel):
    """Admin correction of an existing attendance record. Fields omitted
    here keep their current value — only what's provided is changed."""

    check_in_time: Optional[time] = None
    check_out_time: Optional[time] = None
    reason: str
