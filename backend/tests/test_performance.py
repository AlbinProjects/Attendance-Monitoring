"""
Tests for app.services.performance_service: the 5 PM "start time, not
deadline" rule, work_date/submitted_at separation, missing-performance
detection, and the today/yesterday/older self-service date window.
"""

from datetime import date, datetime, timedelta

import pytest
import pytz
from fastapi import HTTPException

from app.config import get_settings
from app.services import performance_service


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
    monkeypatch.setenv("PERFORMANCE_START_TIME", "17:00")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


IST = pytz.timezone("Asia/Kolkata")


def ist(y, m, d, h, mi):
    return IST.localize(datetime(y, m, d, h, mi))


# -----------------------------------------------------------------------
# Fake Supabase client — supports select (with eq/gte/lt/lte), insert, update
# -----------------------------------------------------------------------

class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    def __init__(self, name, rows=None):
        self.name = name
        self.rows = rows or []
        self._next_id = 1

    def _query(self):
        return FakeQuery(self)


class FakeQuery:
    def __init__(self, table):
        self.table = table
        self.filters = {}
        self.gte_filters = {}
        self.lt_filters = {}
        self.lte_filters = {}
        self.op = None
        self.payload = None

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, field, value):
        self.filters[field] = value
        return self

    def gte(self, field, value):
        self.gte_filters[field] = value
        return self

    def lt(self, field, value):
        self.lt_filters[field] = value
        return self

    def lte(self, field, value):
        self.lte_filters[field] = value
        return self

    def maybe_single(self):
        return self

    def _matches(self, row):
        for k, v in self.filters.items():
            if row.get(k) != v:
                return False
        for k, v in self.gte_filters.items():
            if row.get(k) is None or row.get(k) < v:
                return False
        for k, v in self.lt_filters.items():
            if row.get(k) is None or row.get(k) >= v:
                return False
        for k, v in self.lte_filters.items():
            if row.get(k) is None or row.get(k) > v:
                return False
        return True

    def execute(self):
        if self.op == "select":
            matches = [r for r in self.table.rows if self._matches(r)]
            if self.filters.get("work_date") is not None or (
                "employee_id" in self.filters and len(self.filters) == 2 and not self.gte_filters
            ):
                # single-row lookup style (get_performance_for_date uses
                # exactly employee_id + work_date with maybe_single)
                if len(matches) == 1:
                    return FakeResult(matches[0])
                if len(matches) == 0:
                    return FakeResult(None)
            return FakeResult(matches)

        if self.op == "insert":
            row = dict(self.payload)
            row["id"] = f"row-{self.table._next_id}"
            self.table._next_id += 1
            for existing in self.table.rows:
                if (
                    existing.get("employee_id") == row.get("employee_id")
                    and existing.get("work_date") == row.get("work_date")
                ):
                    raise Exception("duplicate key value violates unique constraint")
            self.table.rows.append(row)
            return FakeResult([row])

        if self.op == "update":
            matches = [r for r in self.table.rows if self._matches(r)]
            for r in matches:
                r.update(self.payload)
            return FakeResult(matches)

        raise AssertionError("unsupported operation")


class FakeClient:
    def __init__(self):
        self.tables = {"performance_updates": FakeTable("performance_updates")}

    def table(self, name):
        return self.tables[name]._query()


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(performance_service, "get_service_client", lambda: client)
    return client


def freeze_office_now(monkeypatch, dt):
    monkeypatch.setattr(performance_service, "get_office_now", lambda settings: dt)
    monkeypatch.setattr(performance_service, "get_office_today", lambda settings: dt.date())


# -----------------------------------------------------------------------
# is_performance_available — the core 5 PM rule
# -----------------------------------------------------------------------

def test_before_5pm_not_available():
    settings = get_settings()
    now = ist(2026, 8, 17, 16, 59)
    assert performance_service.is_performance_available(settings, at=now) is False


def test_exactly_5pm_is_available():
    settings = get_settings()
    now = ist(2026, 8, 17, 17, 0)
    assert performance_service.is_performance_available(settings, at=now) is True


def test_after_5pm_is_available():
    settings = get_settings()
    for hour, minute in [(17, 1), (18, 0), (22, 30), (23, 59)]:
        now = ist(2026, 8, 17, hour, minute)
        assert performance_service.is_performance_available(settings, at=now) is True


def test_no_closing_deadline_available_stays_true_all_night():
    """There is explicitly no deadline — 11:58 PM must be just as
    'available' as 5:01 PM."""
    settings = get_settings()
    late_night = ist(2026, 8, 17, 23, 58)
    assert performance_service.is_performance_available(settings, at=late_night) is True


# -----------------------------------------------------------------------
# get_today_status
# -----------------------------------------------------------------------

def test_today_status_not_available_before_5pm(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 10, 0))
    settings = get_settings()
    result = performance_service.get_today_status("emp-1", settings)
    assert result["status"] == "not_available"
    assert result["record"] is None


def test_today_status_available_after_5pm_unsubmitted(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 19, 0))
    settings = get_settings()
    result = performance_service.get_today_status("emp-1", settings)
    assert result["status"] == "available"


def test_today_status_submitted_after_submission(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 20, 0))
    settings = get_settings()
    performance_service.submit_performance("emp-1", None, {"performance_text": "did stuff"}, settings)
    result = performance_service.get_today_status("emp-1", settings)
    assert result["status"] == "submitted"
    assert result["record"] is not None


# -----------------------------------------------------------------------
# submit_performance — availability gating
# -----------------------------------------------------------------------

def test_submit_today_before_5pm_rejected(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 14, 0))
    settings = get_settings()
    with pytest.raises(HTTPException) as exc_info:
        performance_service.submit_performance("emp-1", None, {"performance_text": "x"}, settings)
    assert exc_info.value.status_code == 403
    assert "5:00 PM" in exc_info.value.detail


def test_submit_today_exactly_at_5pm_succeeds(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 17, 0))
    settings = get_settings()
    row = performance_service.submit_performance("emp-1", None, {"performance_text": "x"}, settings)
    assert row["status"] == "submitted"
    assert row["work_date"] == "2026-08-17"


def test_submit_today_late_evening_still_succeeds_no_deadline(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 23, 50))
    settings = get_settings()
    row = performance_service.submit_performance("emp-1", None, {"performance_text": "x"}, settings)
    assert row["status"] == "submitted"


# -----------------------------------------------------------------------
# work_date vs submitted_at, backdating
# -----------------------------------------------------------------------

def test_work_date_and_submitted_at_never_conflated(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 20, 0))
    settings = get_settings()
    row = performance_service.submit_performance("emp-1", None, {"performance_text": "x"}, settings)
    assert row["work_date"] == "2026-08-17"
    assert row["submitted_at"].startswith("2026-08-17")


def test_submit_yesterday_marks_backdated(fake_client, monkeypatch):
    # "Today" is the 18th; submitting for the 17th (yesterday) at any time
    # should be allowed and marked backdated, since submitted_at's date
    # (18th) differs from work_date (17th).
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 9, 0))
    settings = get_settings()
    yesterday = date(2026, 8, 17)
    row = performance_service.submit_performance(
        "emp-1", yesterday, {"performance_text": "backfilled"}, settings
    )
    assert row["work_date"] == "2026-08-17"
    assert row["status"] == "backdated"
    assert row["submitted_at"].startswith("2026-08-18")


def test_submit_yesterday_allowed_even_before_5pm_today(fake_client, monkeypatch):
    # Yesterday's submission isn't gated by TODAY's 5 PM rule at all.
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 8, 0))
    settings = get_settings()
    yesterday = date(2026, 8, 17)
    row = performance_service.submit_performance("emp-1", yesterday, {"performance_text": "x"}, settings)
    assert row["status"] == "backdated"


def test_submit_older_than_yesterday_rejected(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 20, 0))
    settings = get_settings()
    two_days_ago = date(2026, 8, 16)
    with pytest.raises(HTTPException) as exc_info:
        performance_service.submit_performance("emp-1", two_days_ago, {"performance_text": "x"}, settings)
    assert exc_info.value.status_code == 403
    assert "admin authorization" in exc_info.value.detail.lower()


def test_submit_future_date_rejected(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 20, 0))
    settings = get_settings()
    tomorrow = date(2026, 8, 18)
    with pytest.raises(HTTPException) as exc_info:
        performance_service.submit_performance("emp-1", tomorrow, {"performance_text": "x"}, settings)
    assert exc_info.value.status_code == 400


def test_duplicate_submission_same_work_date_rejected(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 17, 20, 0))
    settings = get_settings()
    performance_service.submit_performance("emp-1", None, {"performance_text": "first"}, settings)
    with pytest.raises(HTTPException) as exc_info:
        performance_service.submit_performance("emp-1", None, {"performance_text": "second"}, settings)
    assert exc_info.value.status_code == 409


# -----------------------------------------------------------------------
# get_missing_dates
# -----------------------------------------------------------------------

def test_missing_dates_flags_unsubmitted_past_days(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 9, 0))
    settings = get_settings()
    # Seed a submission for 2026-08-16 directly (bypassing submit_performance,
    # since that function correctly refuses self-service submissions older
    # than yesterday — this test is only about missing-date detection, not
    # submission-window rules) and leave 2026-08-17 missing.
    fake_client.tables["performance_updates"].rows.append(
        {
            "id": "seed-1",
            "employee_id": "emp-1",
            "work_date": "2026-08-16",
            "status": "submitted",
            "submitted_at": "2026-08-16T20:00:00+05:30",
        }
    )
    missing = performance_service.get_missing_dates(
        "emp-1", settings, joining_date=date(2026, 8, 15)
    )
    missing_dates = {m["work_date"] for m in missing}
    assert "2026-08-17" in missing_dates
    assert "2026-08-16" not in missing_dates
    assert "2026-08-18" not in missing_dates  # today is never "missing"


def test_missing_dates_respects_joining_date(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 9, 0))
    settings = get_settings()
    # Employee joined yesterday — nothing before that should be flagged
    # missing even though the lookback window would otherwise reach back
    # further.
    missing = performance_service.get_missing_dates(
        "emp-1", settings, joining_date=date(2026, 8, 17)
    )
    missing_dates = {m["work_date"] for m in missing}
    assert missing_dates == {"2026-08-17"}


def test_missing_dates_empty_when_all_submitted(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 9, 0))
    settings = get_settings()
    performance_service.submit_performance(
        "emp-1", date(2026, 8, 17), {"performance_text": "x"}, settings
    )
    missing = performance_service.get_missing_dates(
        "emp-1", settings, joining_date=date(2026, 8, 17)
    )
    assert missing == []


# -----------------------------------------------------------------------
# get_history
# -----------------------------------------------------------------------

def test_history_synthesizes_missing_for_unsubmitted_past_days(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 20, 0))
    settings = get_settings()
    performance_service.submit_performance(
        "emp-1", date(2026, 8, 17), {"performance_text": "backfilled"}, settings
    )
    performance_service.submit_performance(
        "emp-1", None, {"performance_text": "today's work"}, settings
    )
    history = performance_service.get_history("emp-1", settings, days=3)
    by_date = {h["work_date"]: h["status"] for h in history}
    assert by_date["2026-08-18"] == "submitted"  # submitted today, at 20:00
    assert by_date["2026-08-17"] == "backdated"  # submitted a day late
    assert by_date["2026-08-16"] == "missing"  # never submitted


def test_history_today_shows_available_when_unsubmitted(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 19, 0))
    settings = get_settings()
    history = performance_service.get_history("emp-1", settings, days=1)
    assert history[0]["work_date"] == "2026-08-18"
    assert history[0]["status"] == "available"


def test_history_today_shows_not_available_before_5pm(fake_client, monkeypatch):
    freeze_office_now(monkeypatch, ist(2026, 8, 18, 10, 0))
    settings = get_settings()
    history = performance_service.get_history("emp-1", settings, days=1)
    assert history[0]["status"] == "not_available"
