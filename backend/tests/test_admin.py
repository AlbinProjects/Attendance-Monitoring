"""
Tests for app.services.admin_service: dashboard stat correctness and
filtering across the attendance/performance/activity admin tables.
"""

from datetime import date, datetime

import pytest
import pytz

from app.config import get_settings
from app.services import activity_service, admin_service, attendance_service
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
    monkeypatch.setenv("DAILY_INACTIVITY_FLAG_MINUTES", "60")
    monkeypatch.setenv("INACTIVITY_START_MINUTES", "10")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


IST = pytz.timezone("Asia/Kolkata")


def ist(y, m, d, h, mi):
    return IST.localize(datetime(y, m, d, h, mi))


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr(admin_service, "get_service_client", lambda: client)
    monkeypatch.setattr(activity_service, "get_service_client", lambda: client)
    monkeypatch.setattr(attendance_service, "get_service_client", lambda: client)
    return client


def freeze_today(monkeypatch, d: date):
    monkeypatch.setattr(admin_service, "get_office_today", lambda settings: d)
    monkeypatch.setattr(
        activity_service, "get_office_now", lambda settings: IST.localize(datetime(d.year, d.month, d.day, 23, 0))
    )


def add_employee(fake_client, **kwargs):
    row = {
        "id": kwargs.get("id"),
        "name": kwargs.get("name"),
        "email": f"{kwargs.get('id')}@company.com",
        "employee_code": kwargs.get("id"),
        "department": kwargs.get("department", "Engineering"),
        "role": kwargs.get("role", "employee"),
        "is_active": kwargs.get("is_active", True),
        "joining_date": kwargs.get("joining_date"),
    }
    fake_client.tables["employees"].rows.append(row)
    return row


def add_attendance(fake_client, **kwargs):
    row = {
        "id": kwargs["id"],
        "employee_id": kwargs["employee_id"],
        "attendance_date": kwargs["attendance_date"],
        "check_in": kwargs.get("check_in"),
        "check_out": kwargs.get("check_out"),
        "status": kwargs.get("status", "present"),
        "check_in_source": kwargs.get("check_in_source", "wifi"),
    }
    fake_client.tables["attendance"].rows.append(row)
    return row


# -----------------------------------------------------------------------
# Dashboard stats
# -----------------------------------------------------------------------

def test_dashboard_counts_present_late_and_absent(fake_client, monkeypatch):
    freeze_today(monkeypatch, date(2026, 8, 18))
    settings = get_settings()

    add_employee(fake_client, id="e1", name="Alice")
    add_employee(fake_client, id="e2", name="Bob")
    add_employee(fake_client, id="e3", name="Carol")  # never checks in -> absent

    add_attendance(fake_client, id="a1", employee_id="e1", attendance_date="2026-08-18", status="present")
    add_attendance(fake_client, id="a2", employee_id="e2", attendance_date="2026-08-18", status="late")

    stats = admin_service.get_dashboard_stats(settings)
    assert stats["total_employees"] == 3
    assert stats["present_today"] == 1
    assert stats["late_today"] == 1
    assert stats["absent_today"] == 1  # Carol: no attendance row today


def test_dashboard_excludes_inactive_employees(fake_client, monkeypatch):
    freeze_today(monkeypatch, date(2026, 8, 18))
    settings = get_settings()
    add_employee(fake_client, id="e1", name="Alice", is_active=True)
    add_employee(fake_client, id="e2", name="Departed", is_active=False)
    stats = admin_service.get_dashboard_stats(settings)
    assert stats["total_employees"] == 1


def test_dashboard_missing_performance_respects_joining_date(fake_client, monkeypatch):
    freeze_today(monkeypatch, date(2026, 8, 18))
    settings = get_settings()
    # Alice joined long ago and didn't submit yesterday -> counted missing.
    add_employee(fake_client, id="e1", name="Alice", joining_date="2020-01-01")
    # Bob joined TODAY -> not eligible for yesterday's missing count.
    add_employee(fake_client, id="e2", name="Bob", joining_date="2026-08-18")

    stats = admin_service.get_dashboard_stats(settings)
    assert stats["missing_performance_count"] == 1


def test_dashboard_missing_performance_excludes_submitted(fake_client, monkeypatch):
    freeze_today(monkeypatch, date(2026, 8, 18))
    settings = get_settings()
    add_employee(fake_client, id="e1", name="Alice", joining_date="2020-01-01")
    fake_client.tables["performance_updates"].rows.append(
        {
            "id": "p1",
            "employee_id": "e1",
            "work_date": "2026-08-17",
            "submitted_at": "2026-08-17T20:00:00+05:30",
            "status": "submitted",
        }
    )
    stats = admin_service.get_dashboard_stats(settings)
    assert stats["missing_performance_count"] == 0


def test_dashboard_inactivity_flags_count(fake_client, monkeypatch):
    freeze_today(monkeypatch, date(2026, 8, 18))
    settings = get_settings()
    add_employee(fake_client, id="e1", name="Alice")
    add_employee(fake_client, id="e2", name="Bob")

    # Alice: checked out with 90 min counted inactivity (via a persisted
    # period) -> flagged (>60).
    add_attendance(
        fake_client,
        id="a1",
        employee_id="e1",
        attendance_date="2026-08-18",
        check_in=ist(2026, 8, 18, 9, 0).isoformat(),
        check_out=ist(2026, 8, 18, 18, 0).isoformat(),
    )
    fake_client.tables["activity_sessions"].rows.append(
        {
            "id": "s1",
            "attendance_id": "a1",
            "employee_id": "e1",
            "counted_duration_seconds": 90 * 60,
        }
    )
    # Bob: short session, no inactivity -> not flagged.
    add_attendance(
        fake_client,
        id="a2",
        employee_id="e2",
        attendance_date="2026-08-18",
        check_in=ist(2026, 8, 18, 9, 0).isoformat(),
        check_out=ist(2026, 8, 18, 9, 30).isoformat(),
    )

    stats = admin_service.get_dashboard_stats(settings)
    assert stats["inactivity_flags_count"] == 1


# -----------------------------------------------------------------------
# Attendance table filters
# -----------------------------------------------------------------------

def test_attendance_table_filters_by_department(fake_client, monkeypatch):
    settings = get_settings()
    add_employee(fake_client, id="e1", name="Alice", department="Engineering")
    add_employee(fake_client, id="e2", name="Bob", department="Sales")
    add_attendance(fake_client, id="a1", employee_id="e1", attendance_date="2026-08-18", status="present")
    add_attendance(fake_client, id="a2", employee_id="e2", attendance_date="2026-08-18", status="present")

    rows = admin_service.get_admin_attendance(settings, department="Sales")
    assert len(rows) == 1
    assert rows[0]["employee_name"] == "Bob"


def test_attendance_table_filters_by_status(fake_client, monkeypatch):
    settings = get_settings()
    add_employee(fake_client, id="e1", name="Alice")
    add_attendance(fake_client, id="a1", employee_id="e1", attendance_date="2026-08-17", status="present")
    add_attendance(fake_client, id="a2", employee_id="e1", attendance_date="2026-08-18", status="late")

    rows = admin_service.get_admin_attendance(settings, status="late")
    assert len(rows) == 1
    assert rows[0]["attendance_date"] == "2026-08-18"


def test_attendance_table_filters_by_inactivity_flag(fake_client, monkeypatch):
    settings = get_settings()
    add_employee(fake_client, id="e1", name="Alice")
    add_employee(fake_client, id="e2", name="Bob")
    add_attendance(
        fake_client,
        id="a1",
        employee_id="e1",
        attendance_date="2026-08-18",
        check_in=ist(2026, 8, 18, 9, 0).isoformat(),
        check_out=ist(2026, 8, 18, 18, 0).isoformat(),
    )
    fake_client.tables["activity_sessions"].rows.append(
        {"id": "s1", "attendance_id": "a1", "employee_id": "e1", "counted_duration_seconds": 90 * 60}
    )
    add_attendance(
        fake_client,
        id="a2",
        employee_id="e2",
        attendance_date="2026-08-18",
        check_in=ist(2026, 8, 18, 9, 0).isoformat(),
        check_out=ist(2026, 8, 18, 9, 30).isoformat(),
    )

    flagged_only = admin_service.get_admin_attendance(settings, inactivity_flag=True)
    assert len(flagged_only) == 1
    assert flagged_only[0]["employee_name"] == "Alice"

    unflagged_only = admin_service.get_admin_attendance(settings, inactivity_flag=False)
    assert len(unflagged_only) == 1
    assert unflagged_only[0]["employee_name"] == "Bob"


def test_attendance_table_includes_inactive_employees_for_history(fake_client, monkeypatch):
    settings = get_settings()
    add_employee(fake_client, id="e1", name="FormerEmployee", is_active=False)
    add_attendance(fake_client, id="a1", employee_id="e1", attendance_date="2026-08-01", status="present")
    rows = admin_service.get_admin_attendance(settings)
    assert len(rows) == 1
    assert rows[0]["employee_name"] == "FormerEmployee"


# -----------------------------------------------------------------------
# Performance table filters
# -----------------------------------------------------------------------

def test_performance_table_filters_by_status_and_department(fake_client, monkeypatch):
    settings = get_settings()
    add_employee(fake_client, id="e1", name="Alice", department="Engineering")
    add_employee(fake_client, id="e2", name="Bob", department="Sales")
    fake_client.tables["performance_updates"].rows.extend(
        [
            {"id": "p1", "employee_id": "e1", "work_date": "2026-08-18", "status": "submitted"},
            {"id": "p2", "employee_id": "e2", "work_date": "2026-08-18", "status": "missing"},
        ]
    )
    rows = admin_service.get_admin_performance(settings, status="missing")
    assert len(rows) == 1
    assert rows[0]["employee_name"] == "Bob"

    rows2 = admin_service.get_admin_performance(settings, department="Engineering")
    assert len(rows2) == 1
    assert rows2[0]["employee_name"] == "Alice"


# -----------------------------------------------------------------------
# Activity table + periods drill-down
# -----------------------------------------------------------------------

def test_activity_table_shape_and_flag(fake_client, monkeypatch):
    settings = get_settings()
    add_employee(fake_client, id="e1", name="Alice")
    add_attendance(
        fake_client,
        id="a1",
        employee_id="e1",
        attendance_date="2026-08-18",
        check_in=ist(2026, 8, 18, 9, 0).isoformat(),
        check_out=ist(2026, 8, 18, 18, 0).isoformat(),
    )
    fake_client.tables["activity_sessions"].rows.append(
        {"id": "s1", "attendance_id": "a1", "employee_id": "e1", "counted_duration_seconds": 90 * 60}
    )
    rows = admin_service.get_admin_activity(settings, flag=True)
    assert len(rows) == 1
    assert rows[0]["employee_name"] == "Alice"
    assert rows[0]["flagged"] is True
    assert "attendance_id" in rows[0]


def test_activity_periods_drilldown(fake_client, monkeypatch):
    fake_client.tables["activity_sessions"].rows.extend(
        [
            {"id": "s1", "attendance_id": "a1", "employee_id": "e1", "started_at": "x", "counted_duration_seconds": 600},
            {"id": "s2", "attendance_id": "a1", "employee_id": "e1", "started_at": "y", "counted_duration_seconds": 300},
            {"id": "s3", "attendance_id": "OTHER", "employee_id": "e1", "started_at": "z", "counted_duration_seconds": 100},
        ]
    )
    periods = activity_service.get_periods_for_attendance("a1")
    assert len(periods) == 2
    assert {p["id"] for p in periods} == {"s1", "s2"}
