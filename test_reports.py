"""
Tests for app.services.reports_service: CSV header/column correctness,
duration formatting, and that filters are passed through to the same
admin_service queries the on-screen tables use.
"""

import csv
import io

import pytest

from app.config import get_settings
from app.services import activity_service, admin_service, attendance_service, reports_service
from tests.fakes import FakeSupabaseClient


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("COMPANY_ALLOWED_IPS", "103.42.196.118")
    monkeypatch.setenv("OFFICE_LATITUDE", "10.0234")
    monkeypatch.setenv("OFFICE_LONGITUDE", "76.3487")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("OFFICE_TIMEZONE", "Asia/Kolkata")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr(admin_service, "get_service_client", lambda: client)
    monkeypatch.setattr(activity_service, "get_service_client", lambda: client)
    monkeypatch.setattr(attendance_service, "get_service_client", lambda: client)
    return client


def parse_csv(content: str):
    reader = csv.reader(io.StringIO(content))
    rows = list(reader)
    return rows[0], rows[1:]  # header, data rows


# -----------------------------------------------------------------------
# Attendance report
# -----------------------------------------------------------------------

def test_attendance_csv_header_matches_spec(fake_client):
    settings = get_settings()
    content = reports_service.generate_attendance_csv(settings)
    header, _ = parse_csv(content)
    assert header == [
        "Employee", "Department", "Date", "Check In", "Check Out",
        "Status", "Source", "Active Time", "Inactivity",
    ]


def test_attendance_csv_formats_row_correctly(fake_client):
    fake_client.tables["employees"].rows.append(
        {"id": "e1", "name": "Alice", "department": "Engineering", "is_active": True}
    )
    fake_client.tables["attendance"].rows.append(
        {
            "id": "a1",
            "employee_id": "e1",
            "attendance_date": "2026-08-17",
            "check_in": "2026-08-17T09:10:00+05:30",
            "check_out": "2026-08-17T18:05:00+05:30",
            "status": "present",
            "check_in_source": "wifi",
        }
    )
    settings = get_settings()
    content = reports_service.generate_attendance_csv(settings)
    _, rows = parse_csv(content)
    assert len(rows) == 1
    employee, dept, date, check_in, check_out, status, source, active, inactivity = rows[0]
    assert employee == "Alice"
    assert dept == "Engineering"
    assert date == "2026-08-17"
    assert check_in == "09:10"
    assert check_out == "18:05"
    assert status == "present"
    assert source == "wifi"
    # 8h55m total session, no recorded inactivity periods -> active ~= total
    assert "h" in active or "m" in active


def test_attendance_csv_respects_department_filter(fake_client):
    fake_client.tables["employees"].rows.extend(
        [
            {"id": "e1", "name": "Alice", "department": "Engineering", "is_active": True},
            {"id": "e2", "name": "Bob", "department": "Sales", "is_active": True},
        ]
    )
    fake_client.tables["attendance"].rows.extend(
        [
            {"id": "a1", "employee_id": "e1", "attendance_date": "2026-08-17", "status": "present"},
            {"id": "a2", "employee_id": "e2", "attendance_date": "2026-08-17", "status": "present"},
        ]
    )
    settings = get_settings()
    content = reports_service.generate_attendance_csv(settings, department="Sales")
    _, rows = parse_csv(content)
    assert len(rows) == 1
    assert rows[0][0] == "Bob"


# -----------------------------------------------------------------------
# Performance report
# -----------------------------------------------------------------------

def test_performance_csv_header_matches_spec(fake_client):
    settings = get_settings()
    content = reports_service.generate_performance_csv(settings)
    header, _ = parse_csv(content)
    assert header == ["Employee", "Department", "Work Date", "Status", "Submitted At", "Performance"]


def test_performance_csv_strips_newlines_from_free_text(fake_client):
    fake_client.tables["employees"].rows.append(
        {"id": "e1", "name": "Alice", "department": "Engineering", "is_active": True}
    )
    fake_client.tables["performance_updates"].rows.append(
        {
            "employee_id": "e1",
            "work_date": "2026-08-17",
            "status": "submitted",
            "submitted_at": "2026-08-17T20:14:00+05:30",
            "performance_text": "Line one\nLine two\r\nLine three",
        }
    )
    settings = get_settings()
    content = reports_service.generate_performance_csv(settings)
    _, rows = parse_csv(content)
    assert "\n" not in rows[0][5]
    assert rows[0][4] == "2026-08-17 20:14"


# -----------------------------------------------------------------------
# Activity report
# -----------------------------------------------------------------------

def test_activity_csv_header_matches_spec(fake_client):
    settings = get_settings()
    content = reports_service.generate_activity_csv(settings)
    header, _ = parse_csv(content)
    assert header == ["Employee", "Date", "Total Session", "Counted Inactivity", "Active Time", "Flag"]


def test_activity_csv_flag_column_is_human_readable(fake_client):
    fake_client.tables["employees"].rows.append({"id": "e1", "name": "Alice", "is_active": True})
    fake_client.tables["attendance"].rows.append(
        {
            "id": "a1",
            "employee_id": "e1",
            "attendance_date": "2026-08-17",
            "check_in": "2026-08-17T09:00:00+05:30",
            "check_out": "2026-08-17T18:00:00+05:30",
        }
    )
    fake_client.tables["activity_sessions"].rows.append(
        {"id": "s1", "attendance_id": "a1", "employee_id": "e1", "counted_duration_seconds": 90 * 60}
    )
    settings = get_settings()
    content = reports_service.generate_activity_csv(settings, flag=True)
    _, rows = parse_csv(content)
    assert len(rows) == 1
    assert rows[0][5] == "Flagged"


# -----------------------------------------------------------------------
# Duration formatting
# -----------------------------------------------------------------------

def test_format_duration_hours_and_minutes():
    assert reports_service._format_duration(7 * 3600 + 35 * 60) == "7h 35m"


def test_format_duration_minutes_only():
    assert reports_service._format_duration(45 * 60) == "45m"


def test_format_duration_none():
    assert reports_service._format_duration(None) == ""
