"""
Tests for app.services.company_config_service: the DB-over-env precedence
resolution for network mode / GPS office location / laptop presence
freshness, and audited settings updates.
"""

import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.services import audit_service, company_config_service
from tests.fakes import FakeSupabaseClient


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "x" * 32)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("OFFICE_LATITUDE", "10.0234")
    monkeypatch.setenv("OFFICE_LONGITUDE", "76.3487")
    monkeypatch.setenv("OFFICE_GPS_RADIUS_METERS", "100")
    monkeypatch.setenv("MAX_GPS_ACCURACY_METERS", "100")
    monkeypatch.setenv("COMPANY_ALLOWED_IPS", "9.9.9.9")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr(company_config_service, "get_service_client", lambda: client)
    monkeypatch.setattr(audit_service, "get_service_client", lambda: client)
    return client


# -----------------------------------------------------------------------
# get_effective_config — DB-over-env precedence
# -----------------------------------------------------------------------

def test_falls_back_to_env_when_no_company_settings_row_exists(fake_client):
    """No row at all (e.g. a fresh/misconfigured DB) -> env defaults,
    never a crash."""
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    assert config.network_mode == "dynamic"
    assert config.office_latitude == 10.0234
    assert config.office_longitude == 76.3487
    assert config.office_gps_radius_meters == 100
    assert config.max_gps_accuracy_meters == 100
    assert config.allowed_ips == ["9.9.9.9"]
    assert config.laptop_presence_freshness_minutes == 5


def test_db_row_with_null_gps_fields_falls_back_to_env(fake_client):
    fake_client.tables["company_settings"].rows.append(
        {
            "id": 1,
            "network_mode": "dynamic",
            "allowed_ips": [],
            "office_latitude": None,
            "office_longitude": None,
            "office_gps_radius_meters": None,
            "max_gps_accuracy_meters": None,
            "laptop_presence_freshness_minutes": None,
        }
    )
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    assert config.office_latitude == 10.0234  # from env, not DB
    assert config.laptop_presence_freshness_minutes == 5  # hardcoded default


def test_db_row_overrides_env_when_values_are_set(fake_client):
    fake_client.tables["company_settings"].rows.append(
        {
            "id": 1,
            "network_mode": "static",
            "allowed_ips": ["1.2.3.4"],
            "office_latitude": 20.5,
            "office_longitude": 78.9,
            "office_gps_radius_meters": 250,
            "max_gps_accuracy_meters": 50,
            "laptop_presence_freshness_minutes": 10,
        }
    )
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    assert config.network_mode == "static"
    assert config.allowed_ips == ["1.2.3.4"]
    assert config.office_latitude == 20.5
    assert config.office_longitude == 78.9
    assert config.office_gps_radius_meters == 250
    assert config.max_gps_accuracy_meters == 50
    assert config.laptop_presence_freshness_minutes == 10


def test_db_error_falls_back_to_env_rather_than_crashing(monkeypatch):
    """A transient Supabase outage must not block ALL attendance
    company-wide — falls back to env defaults instead."""

    class BrokenClient:
        def table(self, _name):
            raise Exception("connection refused")

    monkeypatch.setattr(company_config_service, "get_service_client", lambda: BrokenClient())
    settings = get_settings()
    config = company_config_service.get_effective_config(settings)
    assert config.network_mode == "dynamic"
    assert config.office_latitude == 10.0234


# -----------------------------------------------------------------------
# update_company_settings — partial update + audit
# -----------------------------------------------------------------------

def test_update_only_changes_provided_fields(fake_client):
    fake_client.tables["company_settings"].rows.append(
        {
            "id": 1,
            "network_mode": "dynamic",
            "allowed_ips": [],
            "office_latitude": 10.0,
            "office_longitude": 76.0,
            "office_gps_radius_meters": 100,
            "max_gps_accuracy_meters": 100,
            "laptop_presence_freshness_minutes": 5,
        }
    )
    row = company_config_service.update_company_settings(
        {"network_mode": "static", "allowed_ips": ["103.42.196.118"]}, "super-1", "1.2.3.4"
    )
    assert row["network_mode"] == "static"
    assert row["allowed_ips"] == ["103.42.196.118"]
    # Untouched fields keep their prior value.
    assert row["office_latitude"] == 10.0
    assert row["laptop_presence_freshness_minutes"] == 5


def test_update_writes_audit_log(fake_client):
    fake_client.tables["company_settings"].rows.append(
        {"id": 1, "network_mode": "dynamic", "allowed_ips": []}
    )
    company_config_service.update_company_settings({"network_mode": "static"}, "super-1", "1.2.3.4")
    audit_rows = fake_client.tables["audit_logs"].rows
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "COMPANY_SETTINGS_UPDATED"
    assert audit_rows[0]["old_value"] == {"network_mode": "dynamic"}
    assert audit_rows[0]["new_value"] == {"network_mode": "static"}
    assert audit_rows[0]["performed_by"] == "super-1"


def test_update_with_no_row_raises_500(fake_client):
    with pytest.raises(HTTPException) as exc_info:
        company_config_service.update_company_settings({"network_mode": "static"}, "super-1", None)
    assert exc_info.value.status_code == 500


def test_update_with_empty_payload_is_a_no_op(fake_client):
    fake_client.tables["company_settings"].rows.append({"id": 1, "network_mode": "dynamic"})
    row = company_config_service.update_company_settings({}, "super-1", None)
    assert row["network_mode"] == "dynamic"
    assert fake_client.tables["audit_logs"].rows == []
