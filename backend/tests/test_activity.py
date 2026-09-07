"""
Tests for app.services.activity_service: the 10-minute grace period, the
60-minute daily flag, and the two worked examples from README section 60:

  Example A (same fixed baseline, queried at two different times):
    Last activity: 10:00
    At 10:10 -> counted 0
    At 10:25 -> counted 15

  Example B (three separate, closed inactivity periods):
    10:00 -> 10:08 (8 min gap):  counted 0
    11:00 -> 11:20 (20 min gap): counted 10
    14:00 -> 14:50 (50 min gap): counted 40
    Total: 0 + 10 + 40 = 50 (NOT 8 + 20 + 50 = 78)
"""

from datetime import datetime, timedelta

import pytest
import pytz
from fastapi import HTTPException

from app.config import get_settings
from app.services import activity_service, attendance_service


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
    monkeypatch.setenv("INACTIVITY_START_MINUTES", "10")
    monkeypatch.setenv("DAILY_INACTIVITY_FLAG_MINUTES", "60")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


IST = pytz.timezone("Asia/Kolkata")


def ist(y, m, d, h, mi):
    return IST.localize(datetime(y, m, d, h, mi))


# -----------------------------------------------------------------------
# Fake Supabase client: attendance, activity_heartbeats, activity_sessions
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

    def maybe_single(self):
        return self

    def order(self, *_a, **_k):
        return self

    def _matches(self, row):
        return all(row.get(k) == v for k, v in self.filters.items())

    def execute(self):
        if self.op == "select":
            matches = [r for r in self.table.rows if self._matches(r)]
            if self.table.name in ("attendance", "activity_heartbeats"):
                # these callers always use maybe_single semantics
                if len(matches) == 1:
                    return FakeResult(matches[0])
                if len(matches) == 0:
                    return FakeResult(None)
            return FakeResult(matches)

        if self.op == "insert":
            row = dict(self.payload)
            row["id"] = f"row-{self.table._next_id}"
            self.table._next_id += 1
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
        self.tables = {
            "attendance": FakeTable("attendance"),
            "activity_heartbeats": FakeTable("activity_heartbeats"),
            "activity_sessions": FakeTable("activity_sessions"),
        }

    def table(self, name):
        return self.tables[name]._query()


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(activity_service, "get_service_client", lambda: client)
    monkeypatch.setattr(attendance_service, "get_service_client", lambda: client)
    return client


def seed_open_attendance(fake_client, employee_id, check_in_dt, attendance_date="2026-08-17"):
    row = {
        "id": "att-1",
        "employee_id": employee_id,
        "attendance_date": attendance_date,
        "check_in": check_in_dt.isoformat(),
        "check_out": None,
        "status": "present",
        "check_in_source": "wifi",
    }
    fake_client.tables["attendance"].rows.append(row)
    return row


def freeze_now(monkeypatch, dt):
    monkeypatch.setattr(activity_service, "get_office_now", lambda settings: dt)
    monkeypatch.setattr(activity_service, "get_office_today", lambda settings: dt.date())


# -----------------------------------------------------------------------
# README section 60, Example A — same fixed baseline, queried twice
# -----------------------------------------------------------------------

def test_example_a_ten_minutes_since_baseline_counts_zero(fake_client, monkeypatch):
    check_in = ist(2026, 8, 17, 9, 0)
    seed_open_attendance(fake_client, "emp-1", check_in)
    settings = get_settings()

    # baseline ("last activity") = check-in time = 10:00 in this scenario;
    # reuse check_in as the 10:00 anchor by seeding it at 10:00 directly
    check_in = ist(2026, 8, 17, 10, 0)
    fake_client.tables["attendance"].rows[0]["check_in"] = check_in.isoformat()

    freeze_now(monkeypatch, ist(2026, 8, 17, 10, 10))
    attendance = fake_client.tables["attendance"].rows[0]
    summary = activity_service.get_activity_summary_for_attendance(attendance, settings)
    assert summary["counted_inactivity_seconds"] == 0


def test_example_a_twenty_five_minutes_since_baseline_counts_fifteen(fake_client, monkeypatch):
    check_in = ist(2026, 8, 17, 10, 0)
    seed_open_attendance(fake_client, "emp-1", check_in)
    settings = get_settings()

    freeze_now(monkeypatch, ist(2026, 8, 17, 10, 25))
    attendance = fake_client.tables["attendance"].rows[0]
    summary = activity_service.get_activity_summary_for_attendance(attendance, settings)
    assert summary["counted_inactivity_seconds"] == 15 * 60


# -----------------------------------------------------------------------
# README section 60/61, Example B — three separate closed periods: 0+10+40=50
# -----------------------------------------------------------------------

def test_example_b_three_periods_sum_to_fifty_not_seventy_eight(fake_client, monkeypatch):
    check_in = ist(2026, 8, 17, 10, 0)
    seed_open_attendance(fake_client, "emp-1", check_in)
    settings = get_settings()

    # Period 1: 10:00 -> 10:08 (8 min gap, under the 10-min grace: no
    # period persisted, baseline advances to 10:08).
    freeze_now(monkeypatch, ist(2026, 8, 17, 10, 8))
    r1 = activity_service.record_heartbeat("emp-1", settings)
    assert r1["period_recorded"] is None

    # Between 10:08 and 11:00 the employee is genuinely active (frequent
    # heartbeats, none individually exceeding the grace period) — simulate
    # that directly by advancing the "last seen" pointer without going
    # through record_heartbeat, which would otherwise interpret this big a
    # jump as a single huge gap. This models continuous real activity, not
    # a network glitch.
    activity_service.upsert_heartbeat("att-1", "emp-1", ist(2026, 8, 17, 11, 0))

    # Period 2: 11:00 -> 11:20 (20 min gap): counted 10
    freeze_now(monkeypatch, ist(2026, 8, 17, 11, 20))
    r2 = activity_service.record_heartbeat("emp-1", settings)
    assert r2["period_recorded"]["counted_duration_seconds"] == 10 * 60

    # Active again from 11:20 through to 14:00.
    activity_service.upsert_heartbeat("att-1", "emp-1", ist(2026, 8, 17, 14, 0))

    # Period 3: 14:00 -> 14:50 (50 min gap): counted 40
    freeze_now(monkeypatch, ist(2026, 8, 17, 14, 50))
    r3 = activity_service.record_heartbeat("emp-1", settings)
    assert r3["period_recorded"]["counted_duration_seconds"] == 40 * 60

    # Total counted across the whole day so far: 0 + 10 + 40 = 50, NOT
    # 8 + 20 + 50 = 78 (README's explicit non-example of the wrong answer).
    attendance = fake_client.tables["attendance"].rows[0]
    summary = activity_service.get_activity_summary_for_attendance(attendance, settings)
    assert summary["counted_inactivity_seconds"] == 50 * 60


# -----------------------------------------------------------------------
# record_heartbeat mechanics
# -----------------------------------------------------------------------

def test_heartbeat_requires_check_in(fake_client, monkeypatch):
    freeze_now(monkeypatch, ist(2026, 8, 17, 10, 0))
    settings = get_settings()
    with pytest.raises(HTTPException) as exc_info:
        activity_service.record_heartbeat("emp-1", settings)
    assert exc_info.value.status_code == 400
    assert "check in" in exc_info.value.detail.lower()


def test_heartbeat_rejected_after_check_out(fake_client, monkeypatch):
    check_in = ist(2026, 8, 17, 9, 0)
    row = seed_open_attendance(fake_client, "emp-1", check_in)
    row["check_out"] = ist(2026, 8, 17, 18, 0).isoformat()
    settings = get_settings()
    freeze_now(monkeypatch, ist(2026, 8, 17, 19, 0))
    with pytest.raises(HTTPException) as exc_info:
        activity_service.record_heartbeat("emp-1", settings)
    assert exc_info.value.status_code == 400
    assert "already ended" in exc_info.value.detail.lower()


def test_first_heartbeat_uses_check_in_as_baseline_no_period_if_within_grace(fake_client, monkeypatch):
    check_in = ist(2026, 8, 17, 9, 0)
    seed_open_attendance(fake_client, "emp-1", check_in)
    settings = get_settings()
    freeze_now(monkeypatch, ist(2026, 8, 17, 9, 5))  # 5 min after check-in
    result = activity_service.record_heartbeat("emp-1", settings)
    assert result["period_recorded"] is None


def test_first_heartbeat_long_after_check_in_creates_period(fake_client, monkeypatch):
    """If the employee doesn't touch the browser for 20 minutes right
    after checking in, that gap counts too — check-in time is the
    baseline for the very first heartbeat."""
    check_in = ist(2026, 8, 17, 9, 0)
    seed_open_attendance(fake_client, "emp-1", check_in)
    settings = get_settings()
    freeze_now(monkeypatch, ist(2026, 8, 17, 9, 20))
    result = activity_service.record_heartbeat("emp-1", settings)
    assert result["period_recorded"]["counted_duration_seconds"] == 10 * 60  # 20 - 10 grace


def test_heartbeat_at_normal_cadence_never_creates_periods(fake_client, monkeypatch):
    """Simulates continuous activity: heartbeats every 45s should never
    trigger an inactivity period."""
    check_in = ist(2026, 8, 17, 9, 0)
    seed_open_attendance(fake_client, "emp-1", check_in)
    settings = get_settings()
    t = ist(2026, 8, 17, 9, 0)
    for _ in range(20):
        t = t + timedelta(seconds=45)
        freeze_now(monkeypatch, t)
        result = activity_service.record_heartbeat("emp-1", settings)
        assert result["period_recorded"] is None


# -----------------------------------------------------------------------
# 60-minute daily flag
# -----------------------------------------------------------------------

def test_not_flagged_at_exactly_sixty_minutes_counted(fake_client, monkeypatch):
    """Boundary: exactly 60 min counted should NOT flag (flag is for
    counted > 60, i.e. strictly more than the threshold)."""
    check_in = ist(2026, 8, 17, 9, 0)
    seed_open_attendance(fake_client, "emp-1", check_in)
    settings = get_settings()
    # One long gap: 70 minutes total -> 60 counted (70 - 10 grace)
    freeze_now(monkeypatch, ist(2026, 8, 17, 10, 10))  # 70 min after 09:00
    activity_service.record_heartbeat("emp-1", settings)
    attendance = fake_client.tables["attendance"].rows[0]
    summary = activity_service.get_activity_summary_for_attendance(attendance, settings)
    assert summary["counted_inactivity_seconds"] == 60 * 60
    assert summary["flagged"] is False


def test_flagged_when_counted_exceeds_sixty_minutes(fake_client, monkeypatch):
    check_in = ist(2026, 8, 17, 9, 0)
    seed_open_attendance(fake_client, "emp-1", check_in)
    settings = get_settings()
    # 71 minutes total -> 61 counted
    freeze_now(monkeypatch, ist(2026, 8, 17, 10, 11))
    activity_service.record_heartbeat("emp-1", settings)
    attendance = fake_client.tables["attendance"].rows[0]
    summary = activity_service.get_activity_summary_for_attendance(attendance, settings)
    assert summary["counted_inactivity_seconds"] == 61 * 60
    assert summary["flagged"] is True


# -----------------------------------------------------------------------
# Summary shape / active time calculation
# -----------------------------------------------------------------------

def test_active_session_seconds_equals_total_minus_counted(fake_client, monkeypatch):
    check_in = ist(2026, 8, 17, 9, 0)
    row = seed_open_attendance(fake_client, "emp-1", check_in)
    row["check_out"] = ist(2026, 8, 17, 18, 0).isoformat()  # 9h session
    settings = get_settings()

    # Seed one 30-minute-counted inactivity period directly.
    fake_client.tables["activity_sessions"].rows.append(
        {
            "id": "period-1",
            "attendance_id": "att-1",
            "employee_id": "emp-1",
            "started_at": ist(2026, 8, 17, 12, 0).isoformat(),
            "ended_at": ist(2026, 8, 17, 12, 40).isoformat(),
            "duration_seconds": 40 * 60,
            "counted_duration_seconds": 30 * 60,
        }
    )
    # The employee was active right up until checkout (heartbeats close to
    # 18:00), so the "tail" (last heartbeat -> checkout) contributes
    # nothing extra on top of the one seeded period. Without this, the
    # summary would correctly (but not what this test is isolating) treat
    # the entire rest of the day as one giant unmonitored gap, since no
    # heartbeat trail exists otherwise — see the next test for that case.
    activity_service.upsert_heartbeat("att-1", "emp-1", ist(2026, 8, 17, 17, 55))

    summary = activity_service.get_activity_summary_for_attendance(row, settings)
    assert summary["total_session_seconds"] == 9 * 3600
    assert summary["counted_inactivity_seconds"] == 30 * 60
    assert summary["active_session_seconds"] == 9 * 3600 - 30 * 60


def test_no_heartbeat_all_day_treats_whole_session_as_inactive_tail(fake_client, monkeypatch):
    """If literally no heartbeat was ever sent (browser tab never
    registered any activity event all day), the entire session minus the
    initial grace period is correctly counted as inactive — this is the
    honest, documented limitation of browser-only activity detection (see
    README 'Important limitation of browser activity'), not a bug."""
    check_in = ist(2026, 8, 17, 9, 0)
    row = seed_open_attendance(fake_client, "emp-1", check_in)
    row["check_out"] = ist(2026, 8, 17, 18, 0).isoformat()  # 9h session
    settings = get_settings()

    summary = activity_service.get_activity_summary_for_attendance(row, settings)
    # 9h total, minus the 10-minute grace period once
    assert summary["counted_inactivity_seconds"] == (9 * 3600) - (10 * 60)
    assert summary["flagged"] is True


def test_no_attendance_returns_not_checked_in_shape(fake_client):
    settings = get_settings()
    summary = activity_service.get_activity_summary_for_attendance(None, settings)
    assert summary["checked_in"] is False
    assert summary["counted_inactivity_seconds"] == 0
    assert summary["flagged"] is False
