"""
Tests for app.services.audit_service.get_audit_logs: filtering and the
absence of any delete capability (there is deliberately no
delete_audit_log function anywhere in this module).
"""

import pytest

from app.config import get_settings
from app.services import audit_service
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
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr(audit_service, "get_service_client", lambda: client)
    return client


def seed_logs(fake_client):
    fake_client.tables["audit_logs"].rows.extend(
        [
            {
                "id": "log-1",
                "employee_id": "e1",
                "attendance_id": "a1",
                "action": "CHECK_IN",
                "performed_by": "e1",
                "created_at": "2026-08-17T09:10:00+05:30",
            },
            {
                "id": "log-2",
                "employee_id": "e1",
                "attendance_id": "a1",
                "action": "ADMIN_ATTENDANCE_UPDATED",
                "performed_by": "admin-1",
                "created_at": "2026-08-18T10:00:00+05:30",
            },
            {
                "id": "log-3",
                "employee_id": "e2",
                "attendance_id": "a2",
                "action": "CHECK_IN",
                "performed_by": "e2",
                "created_at": "2026-08-18T09:05:00+05:30",
            },
        ]
    )


def test_filters_by_employee_id(fake_client):
    seed_logs(fake_client)
    rows = audit_service.get_audit_logs(employee_id="e1")
    assert {r["id"] for r in rows} == {"log-1", "log-2"}


def test_filters_by_action(fake_client):
    seed_logs(fake_client)
    rows = audit_service.get_audit_logs(action="ADMIN_ATTENDANCE_UPDATED")
    assert {r["id"] for r in rows} == {"log-2"}


def test_filters_by_performed_by(fake_client):
    seed_logs(fake_client)
    rows = audit_service.get_audit_logs(performed_by="admin-1")
    assert {r["id"] for r in rows} == {"log-2"}


def test_filters_by_date(fake_client):
    seed_logs(fake_client)
    rows = audit_service.get_audit_logs(on_date="2026-08-18")
    assert {r["id"] for r in rows} == {"log-2", "log-3"}


def test_results_sorted_most_recent_first(fake_client):
    seed_logs(fake_client)
    rows = audit_service.get_audit_logs()
    created_ats = [r["created_at"] for r in rows]
    assert created_ats == sorted(created_ats, reverse=True)


def test_no_delete_function_exists():
    """Enforces README 'Do not provide normal deletion of audit records'
    at the module level — this isn't a runtime behavior test so much as a
    guardrail against ever adding one by accident."""
    assert not hasattr(audit_service, "delete_audit_log")
