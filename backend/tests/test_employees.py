"""
Tests for app.services.employees_service: employee provisioning (via the
fake auth.admin API, matching the real supabase-py method shapes verified
against the installed package), audited role/disable changes, and search.
"""

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.services import audit_service, employees_service
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
    monkeypatch.setattr(employees_service, "get_service_client", lambda: client)
    monkeypatch.setattr(audit_service, "get_service_client", lambda: client)
    return client


# -----------------------------------------------------------------------
# create_employee
# -----------------------------------------------------------------------

def test_create_employee_provisions_real_auth_user(fake_client):
    payload = {
        "employee_code": "EMP010",
        "name": "New Hire",
        "email": "newhire@company.com",
        "department": "Engineering",
        "role": "employee",
    }
    row, temp_password = employees_service.create_employee(payload, "super-admin-1", "103.42.196.118")

    assert len(fake_client.auth.admin.created_users) == 1
    created = fake_client.auth.admin.created_users[0]
    assert created["email"] == "newhire@company.com"
    assert created["email_confirm"] is True

    assert row["employee_code"] == "EMP010"
    assert row["auth_user_id"] == created["id"]
    assert row["is_active"] is True
    assert temp_password  # a password was generated and returned


def test_create_employee_uses_provided_password_if_given(fake_client):
    payload = {
        "employee_code": "EMP011",
        "name": "New Hire",
        "email": "nh2@company.com",
        "password": "chosen-password-123",
    }
    _, temp_password = employees_service.create_employee(payload, "super-admin-1", None)
    assert temp_password == "chosen-password-123"
    assert fake_client.auth.admin.created_users[0]["password"] == "chosen-password-123"


def test_create_employee_writes_audit_log(fake_client):
    payload = {"employee_code": "EMP012", "name": "New Hire", "email": "nh3@company.com"}
    row, _ = employees_service.create_employee(payload, "super-admin-1", "103.42.196.118")
    audit_rows = fake_client.tables["audit_logs"].rows
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "EMPLOYEE_CREATED"
    assert audit_rows[0]["employee_id"] == row["id"]
    assert audit_rows[0]["performed_by"] == "super-admin-1"


def test_create_employee_defaults_to_employee_role(fake_client):
    payload = {"employee_code": "EMP013", "name": "New Hire", "email": "nh4@company.com"}
    row, _ = employees_service.create_employee(payload, "super-admin-1", None)
    assert row["role"] == "employee"


def test_create_employee_duplicate_employee_code_rejected(fake_client):
    fake_client.tables["employees"].rows.append(
        {"id": "existing", "employee_code": "DUP001", "email": "existing@company.com"}
    )

    # Simulate the DB unique constraint by making insert fail when the
    # employee_code already exists (mirroring the real unique index).
    original_execute = fake_client.tables["employees"]._query

    def query_with_constraint():
        query = original_execute()
        real_execute = query.execute

        def guarded_execute():
            if query.op == "insert":
                for existing in fake_client.tables["employees"].rows:
                    if existing.get("employee_code") == query.payload.get("employee_code"):
                        raise Exception("duplicate key value violates unique constraint")
            return real_execute()

        query.execute = guarded_execute
        return query

    fake_client.tables["employees"]._query = query_with_constraint

    payload = {"employee_code": "DUP001", "name": "Someone", "email": "someone@company.com"}
    with pytest.raises(HTTPException) as exc_info:
        employees_service.create_employee(payload, "super-admin-1", None)
    assert exc_info.value.status_code == 409


def test_create_employee_auth_failure_raises_400(fake_client, monkeypatch):
    def failing_create_user(_attrs):
        raise Exception("auth provider down")

    fake_client.auth.admin.create_user = failing_create_user
    payload = {"employee_code": "EMP014", "name": "New Hire", "email": "nh5@company.com"}
    with pytest.raises(HTTPException) as exc_info:
        employees_service.create_employee(payload, "super-admin-1", None)
    assert exc_info.value.status_code == 400


# -----------------------------------------------------------------------
# update_employee
# -----------------------------------------------------------------------

def _seed_employee(fake_client, **overrides):
    row = {
        "id": "emp-1",
        "auth_user_id": "auth-1",
        "employee_code": "EMP001",
        "name": "Alice",
        "email": "alice@company.com",
        "department": "Engineering",
        "role": "employee",
        "is_active": True,
    }
    row.update(overrides)
    fake_client.tables["employees"].rows.append(row)
    return row


def test_update_employee_not_found_raises_404(fake_client):
    with pytest.raises(HTTPException) as exc_info:
        employees_service.update_employee("nonexistent", {"name": "X"}, "admin-1", None)
    assert exc_info.value.status_code == 404


def test_update_employee_plain_field_change_audited_as_updated(fake_client):
    _seed_employee(fake_client)
    row = employees_service.update_employee("emp-1", {"department": "Sales"}, "admin-1", None)
    assert row["department"] == "Sales"
    actions = [r["action"] for r in fake_client.tables["audit_logs"].rows]
    assert actions == ["EMPLOYEE_UPDATED"]


def test_update_employee_role_change_audited_distinctly(fake_client):
    _seed_employee(fake_client)
    row = employees_service.update_employee("emp-1", {"role": "admin"}, "super-1", "1.2.3.4")
    assert row["role"] == "admin"
    audit = fake_client.tables["audit_logs"].rows[0]
    assert audit["action"] == "EMPLOYEE_ROLE_CHANGED"
    assert audit["old_value"] == {"role": "employee"}
    assert audit["new_value"] == {"role": "admin"}


def test_update_employee_disable_audited_and_bans_auth_user(fake_client):
    _seed_employee(fake_client)
    row = employees_service.update_employee("emp-1", {"is_active": False}, "super-1", None)
    assert row["is_active"] is False
    audit = fake_client.tables["audit_logs"].rows[0]
    assert audit["action"] == "EMPLOYEE_DISABLED"
    assert fake_client.auth.admin.banned["auth-1"] == employees_service.BAN_DURATION_PERMANENT


def test_update_employee_enable_unbans_auth_user(fake_client):
    _seed_employee(fake_client, is_active=False)
    employees_service.update_employee("emp-1", {"is_active": True}, "super-1", None)
    assert fake_client.auth.admin.banned["auth-1"] == employees_service.BAN_DURATION_NONE


def test_update_employee_no_fields_changed_writes_no_audit(fake_client):
    _seed_employee(fake_client)
    employees_service.update_employee("emp-1", {}, "super-1", None)
    assert fake_client.tables["audit_logs"].rows == []


# -----------------------------------------------------------------------
# list_employees
# -----------------------------------------------------------------------

def test_list_employees_search_matches_name_email_or_code(fake_client):
    _seed_employee(fake_client, id="e1", name="Alice Smith", email="alice@company.com", employee_code="EMP001")
    _seed_employee(fake_client, id="e2", name="Bob Jones", email="bob@company.com", employee_code="EMP002")

    results = employees_service.list_employees(search="alice")
    assert [r["id"] for r in results] == ["e1"]

    results2 = employees_service.list_employees(search="EMP002")
    assert [r["id"] for r in results2] == ["e2"]


def test_list_employees_filters_by_department_and_active(fake_client):
    _seed_employee(fake_client, id="e1", name="Alice", department="Engineering", is_active=True)
    _seed_employee(fake_client, id="e2", name="Bob", department="Sales", is_active=False)

    eng_only = employees_service.list_employees(department="Engineering")
    assert [r["id"] for r in eng_only] == ["e1"]

    active_only = employees_service.list_employees(is_active=True)
    assert [r["id"] for r in active_only] == ["e1"]
