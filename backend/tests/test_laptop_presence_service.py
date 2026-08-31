"""
Tests for app.services.laptop_presence_service: upsert-on-ping behavior
and the freshness window used to gate phone check-in.
"""

from datetime import datetime, timedelta

import pytest
import pytz

from app.config import get_settings
from app.services import laptop_presence_service
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
    monkeypatch.setenv("OFFICE_TIMEZONE", "Asia/Kolkata")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeSupabaseClient()
    monkeypatch.setattr(laptop_presence_service, "get_service_client", lambda: client)
    return client


IST = pytz.timezone("Asia/Kolkata")


def freeze_now(monkeypatch, dt):
    monkeypatch.setattr(laptop_presence_service, "get_office_now", lambda settings: dt)


# -----------------------------------------------------------------------
# ping / get_presence
# -----------------------------------------------------------------------

def test_ping_creates_row_for_new_employee(fake_client):
    settings = get_settings()
    laptop_presence_service.ping("emp-1", settings)
    row = laptop_presence_service.get_presence("emp-1")
    assert row is not None
    assert row["employee_id"] == "emp-1"


def test_ping_updates_existing_row_rather_than_duplicating(fake_client, monkeypatch):
    settings = get_settings()
    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 0)))
    laptop_presence_service.ping("emp-1", settings)

    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 5)))
    laptop_presence_service.ping("emp-1", settings)

    assert len(fake_client.tables["laptop_presence"].rows) == 1
    row = laptop_presence_service.get_presence("emp-1")
    assert row["last_seen_at"].startswith("2026-08-17T09:05")


def test_get_presence_none_when_never_pinged(fake_client):
    assert laptop_presence_service.get_presence("emp-never-pinged") is None


# -----------------------------------------------------------------------
# has_recent_presence
# -----------------------------------------------------------------------

def test_has_recent_presence_false_when_never_pinged(fake_client):
    settings = get_settings()
    assert laptop_presence_service.has_recent_presence("emp-1", 5, settings) is False


def test_has_recent_presence_true_within_freshness_window(fake_client, monkeypatch):
    settings = get_settings()
    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 0)))
    laptop_presence_service.ping("emp-1", settings)

    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 4)))  # 4 min later
    assert laptop_presence_service.has_recent_presence("emp-1", 5, settings) is True


def test_has_recent_presence_false_outside_freshness_window(fake_client, monkeypatch):
    settings = get_settings()
    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 0)))
    laptop_presence_service.ping("emp-1", settings)

    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 6)))  # 6 min later
    assert laptop_presence_service.has_recent_presence("emp-1", 5, settings) is False


def test_has_recent_presence_exactly_at_freshness_boundary_is_true(fake_client, monkeypatch):
    """Inclusive boundary: exactly at the freshness limit still counts."""
    settings = get_settings()
    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 0)))
    laptop_presence_service.ping("emp-1", settings)

    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 5)))  # exactly 5 min later
    assert laptop_presence_service.has_recent_presence("emp-1", 5, settings) is True


def test_has_recent_presence_respects_custom_freshness_minutes(fake_client, monkeypatch):
    settings = get_settings()
    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 0)))
    laptop_presence_service.ping("emp-1", settings)

    freeze_now(monkeypatch, IST.localize(datetime(2026, 8, 17, 9, 8)))  # 8 min later
    assert laptop_presence_service.has_recent_presence("emp-1", 10, settings) is True
    assert laptop_presence_service.has_recent_presence("emp-1", 5, settings) is False
