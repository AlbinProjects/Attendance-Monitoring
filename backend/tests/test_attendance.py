"""
Tests for app.services.attendance_service: server-side time source, status
calculation boundary, and duplicate/ordering protections.

Uses a fake Supabase client so no network calls happen. The fake mimics
enough of the supabase-py v2 fluent interface for these tests
(.table().select()/.insert()/.update()....eq()...maybe_single().execute()).
"""

from datetime import date, datetime, time as dtime, timedelta

import pytest
import pytz
from fastapi import HTTPException

from app.config import get_settings
from app.services import attendance_service, audit_service, company_config_service, laptop_presence_service


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
    monkeypatch.setenv("OFFICE_START_TIME", "09:00")
    monkeypatch.setenv("LATE_THRESHOLD_MINUTES", "15")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# -----------------------------------------------------------------------
# Fake Supabase client supporting select/insert/update
# -----------------------------------------------------------------------

class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeTable:
    """In-memory stand-in for one Supabase table, keyed by a synthetic
    incrementing id, supporting the small subset of the fluent query
    builder attendance_service actually uses."""

    def __init__(self, name, rows=None):
        self.name = name
        self.rows = rows or []
        self._next_id = 1

    def _query(self):
        return FakeQuery(self)


class FakeQuery:
    def __init__(self, table: FakeTable):
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

    def execute(self):
        if self.op == "select":
            matches = [
                r for r in self.table.rows
                if all(r.get(k) == v for k, v in self.filters.items())
            ]
            # maybe_single-style: return first match or None; list callers
            # (history) just get the list either way via .data
            if len(matches) == 1:
                return FakeResult(matches[0])
            if len(matches) == 0:
                return FakeResult(None)
            return FakeResult(matches)

        if self.op == "insert":
            row = dict(self.payload)
            row["id"] = f"row-{self.table._next_id}"
            self.table._next_id += 1
            # simulate the (employee_id, attendance_date) unique constraint
            # — this constraint only exists on the real `attendance` table,
            # so only enforce it here for that table.
            if self.table.name == "attendance":
                for existing in self.table.rows:
                    if (
                        existing.get("employee_id") == row.get("employee_id")
                        and existing.get("attendance_date") == row.get("attendance_date")
                    ):
                        raise Exception("duplicate key value violates unique constraint")
            self.table.rows.append(row)
            return FakeResult([row])

        if self.op == "update":
            matches = [
                r for r in self.table.rows
                if all(r.get(k) == v for k, v in self.filters.items())
            ]
            for r in matches:
                r.update(self.payload)
            return FakeResult(matches)

        raise AssertionError("unsupported operation in FakeQuery")


class FakeClient:
    def __init__(self):
        self.tables = {
            "attendance": FakeTable("attendance"),
            "audit_logs": FakeTable("audit_logs"),
            "company_settings": FakeTable("company_settings"),
            "laptop_presence": FakeTable("laptop_presence"),
        }
        # Default: dynamic network mode (GPS-only), matching Phase 13
        # behavior — individual tests override network_mode to "static"
        # to exercise the Phase 14 combined IP+GPS path.
        self.tables["company_settings"].rows.append(
            {
                "id": 1,
                "network_mode": "dynamic",
                "allowed_ips": [],
                "office_latitude": None,
                "office_longitude": None,
                "office_gps_radius_meters": None,
                "max_gps_accuracy_meters": None,
                "laptop_presence_freshness_minutes": 5,
            }
        )

    def table(self, name):
        return self.tables[name]._query()


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(attendance_service, "get_service_client", lambda: client)
    monkeypatch.setattr(audit_service, "get_service_client", lambda: client)
    monkeypatch.setattr(company_config_service, "get_service_client", lambda: client)
    monkeypatch.setattr(laptop_presence_service, "get_service_client", lambda: client)
    # Default happy path: every standard test employee has a fresh laptop
    # ping already recorded, so existing check-in tests don't need to
    # know about the Phase 14 laptop-presence gate unless they're
    # specifically testing it.
    now_iso = attendance_service.get_office_now(get_settings()).isoformat()
    for emp_id in ("emp-1", "emp-2"):
        client.tables["laptop_presence"].rows.append({"employee_id": emp_id, "last_seen_at": now_iso})
    return client


# -----------------------------------------------------------------------
# Server-side time source
# -----------------------------------------------------------------------

def test_office_now_uses_configured_timezone_not_utc():
    settings = get_settings()
    now = attendance_service.get_office_now(settings)
    assert str(now.tzinfo) == "Asia/Kolkata" or now.tzinfo.zone == "Asia/Kolkata"


# -----------------------------------------------------------------------
# Status boundary: present vs late
# -----------------------------------------------------------------------

def _ist(hour, minute):
    tz = pytz.timezone("Asia/Kolkata")
    return tz.localize(datetime(2026, 8, 17, hour, minute))


def test_check_in_exactly_at_office_start_is_present():
    settings = get_settings()
    assert attendance_service.determine_attendance_status(_ist(9, 0), settings) == "present"


def test_check_in_exactly_at_threshold_boundary_is_present():
    # office_start=09:00, late_threshold=15min -> 09:15 is still present
    settings = get_settings()
    assert attendance_service.determine_attendance_status(_ist(9, 15), settings) == "present"


def test_check_in_one_minute_past_threshold_is_late():
    settings = get_settings()
    assert attendance_service.determine_attendance_status(_ist(9, 16), settings) == "late"


def test_check_in_well_before_start_is_present():
    settings = get_settings()
    assert attendance_service.determine_attendance_status(_ist(8, 30), settings) == "present"


def test_check_in_well_after_threshold_is_late():
    settings = get_settings()
    assert attendance_service.determine_attendance_status(_ist(11, 0), settings) == "late"


# -----------------------------------------------------------------------
# Check-in / check-out flow (Phase 13: GPS-verified)
# -----------------------------------------------------------------------

# Office coordinates match the env fixture's OFFICE_LATITUDE/LONGITUDE
# (10.0234, 76.3487) exactly, so these are "at the office" (distance 0).
OFFICE_LAT = 10.0234
OFFICE_LON = 76.3487
GOOD_ACCURACY = 15.0


def test_check_in_creates_row_with_server_derived_fields(fake_client):
    settings = get_settings()
    row = attendance_service.create_check_in(
        "emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings, client_ip="103.42.196.118"
    )
    assert row["employee_id"] == "emp-1"
    assert row["check_in_source"] == "gps"
    assert row["check_in_ip"] == "103.42.196.118"  # informational only, not authorization
    assert row["check_in_latitude"] == OFFICE_LAT
    assert row["check_in_longitude"] == OFFICE_LON
    assert row["check_in_accuracy_meters"] == GOOD_ACCURACY
    assert row["check_in_distance_meters"] < 1.0  # essentially at the office
    assert row["status"] in ("present", "late")
    assert row.get("check_out") is None


def test_check_in_writes_audit_log_with_location_metadata(fake_client):
    settings = get_settings()
    attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    audit_rows = fake_client.tables["audit_logs"].rows
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "CHECK_IN"
    assert audit_rows[0]["employee_id"] == "emp-1"
    assert audit_rows[0]["new_value"]["location_verified"] is True
    assert "distance_meters" in audit_rows[0]["new_value"]
    assert "accuracy_meters" in audit_rows[0]["new_value"]


def test_duplicate_check_in_same_day_rejected(fake_client):
    settings = get_settings()
    attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert exc_info.value.status_code == 409
    assert "already checked in" in exc_info.value.detail.lower()


def test_check_out_without_check_in_rejected(fake_client):
    settings = get_settings()
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_out("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert exc_info.value.status_code == 400
    assert "check-in was not found" in exc_info.value.detail.lower()


def test_check_out_after_check_in_succeeds(fake_client):
    settings = get_settings()
    attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    row = attendance_service.create_check_out("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert row["check_out"] is not None
    assert row["check_out_source"] == "gps"
    assert row["check_out_distance_meters"] < 1.0


def test_duplicate_check_out_rejected(fake_client):
    settings = get_settings()
    attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    attendance_service.create_check_out("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_out("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert exc_info.value.status_code == 409
    assert "already checked out" in exc_info.value.detail.lower()


def test_different_employees_can_check_in_same_day(fake_client):
    settings = get_settings()
    row1 = attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    row2 = attendance_service.create_check_in("emp-2", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert row1["id"] != row2["id"]


def test_check_out_writes_audit_log(fake_client):
    settings = get_settings()
    attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    attendance_service.create_check_out("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    actions = [r["action"] for r in fake_client.tables["audit_logs"].rows]
    assert actions == ["CHECK_IN", "CHECK_OUT"]


# -----------------------------------------------------------------------
# GPS location verification (Phase 13)
# -----------------------------------------------------------------------

def test_check_in_far_outside_office_radius_rejected(fake_client):
    settings = get_settings()
    # ~1.1km away (roughly 0.01 degrees latitude) — well outside the
    # default 100m radius.
    far_lat = OFFICE_LAT + 0.01
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in("emp-1", far_lat, OFFICE_LON, GOOD_ACCURACY, settings)
    assert exc_info.value.status_code == 403
    assert "permitted office area" in exc_info.value.detail.lower()


def test_check_in_exactly_at_office_succeeds(fake_client):
    settings = get_settings()
    row = attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert row["check_in_distance_meters"] < 1.0


def test_check_in_just_inside_radius_boundary_succeeds(fake_client):
    """~90m north of the office (default radius is 100m) should pass."""
    settings = get_settings()
    # 1 degree of latitude is ~111,320m, so 90m ≈ 0.000808 degrees.
    nearby_lat = OFFICE_LAT + (90 / 111_320)
    row = attendance_service.create_check_in("emp-1", nearby_lat, OFFICE_LON, GOOD_ACCURACY, settings)
    assert row["check_in_distance_meters"] < 100.0


def test_check_in_just_outside_radius_boundary_rejected(fake_client):
    """~110m north of the office (default radius is 100m) should fail."""
    settings = get_settings()
    far_lat = OFFICE_LAT + (110 / 111_320)
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in("emp-1", far_lat, OFFICE_LON, GOOD_ACCURACY, settings)
    assert exc_info.value.status_code == 403


def test_check_in_poor_gps_accuracy_rejected(fake_client):
    settings = get_settings()
    # Default MAX_GPS_ACCURACY_METERS is 100; 150 exceeds it even though
    # the coordinates themselves are exactly at the office.
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, 150.0, settings)
    assert exc_info.value.status_code == 403
    assert "accuracy" in exc_info.value.detail.lower()


def test_check_in_accuracy_exactly_at_threshold_succeeds(fake_client):
    settings = get_settings()
    row = attendance_service.create_check_in(
        "emp-1", OFFICE_LAT, OFFICE_LON, settings.max_gps_accuracy_meters, settings
    )
    assert row["check_in_accuracy_meters"] == settings.max_gps_accuracy_meters


def test_check_out_outside_office_rejected(fake_client):
    settings = get_settings()
    attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    far_lat = OFFICE_LAT + 0.01
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_out("emp-1", far_lat, OFFICE_LON, GOOD_ACCURACY, settings)
    assert exc_info.value.status_code == 403
    # Checked in successfully but not checked out — the row should still
    # reflect only the check-in, not a partial/incorrect check-out.
    row = attendance_service.get_attendance_for_date("emp-1", attendance_service.get_office_today(settings))
    assert row.get("check_out") is None


# -----------------------------------------------------------------------
# Manual attendance creation (admin)
# -----------------------------------------------------------------------

def test_create_manual_attendance_requires_reason(fake_client):
    settings = get_settings()
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_manual_attendance(
            employee_id="emp-1",
            attendance_date=date(2026, 8, 17),
            check_in_time=dtime(9, 10),
            check_out_time=dtime(18, 0),
            reason="   ",
            marked_by_employee_id="admin-1",
            ip_address=None,
            settings=settings,
        )
    assert exc_info.value.status_code == 400
    assert "reason" in exc_info.value.detail.lower()


def test_create_manual_attendance_checkout_without_checkin_rejected(fake_client):
    settings = get_settings()
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_manual_attendance(
            employee_id="emp-1",
            attendance_date=date(2026, 8, 17),
            check_in_time=None,
            check_out_time=dtime(18, 0),
            reason="WiFi outage",
            marked_by_employee_id="admin-1",
            ip_address=None,
            settings=settings,
        )
    assert exc_info.value.status_code == 400


def test_create_manual_attendance_sets_admin_source_and_manual_status(fake_client):
    settings = get_settings()
    row = attendance_service.create_manual_attendance(
        employee_id="emp-1",
        attendance_date=date(2026, 8, 17),
        check_in_time=dtime(9, 10),
        check_out_time=dtime(18, 0),
        reason="Company WiFi outage",
        marked_by_employee_id="admin-1",
        ip_address="1.2.3.4",
        settings=settings,
    )
    assert row["status"] == "manual"
    assert row["check_in_source"] == "admin"
    assert row["check_out_source"] == "admin"
    assert row["marked_by"] == "admin-1"
    assert row["reason"] == "Company WiFi outage"
    assert row["check_in"].startswith("2026-08-17T09:10")
    assert row["check_out"].startswith("2026-08-17T18:00")


def test_create_manual_attendance_writes_audit_log(fake_client):
    settings = get_settings()
    row = attendance_service.create_manual_attendance(
        employee_id="emp-1",
        attendance_date=date(2026, 8, 17),
        check_in_time=dtime(9, 10),
        check_out_time=dtime(18, 0),
        reason="WiFi outage",
        marked_by_employee_id="admin-1",
        ip_address="1.2.3.4",
        settings=settings,
    )
    audit_rows = fake_client.tables["audit_logs"].rows
    assert len(audit_rows) == 1
    assert audit_rows[0]["action"] == "ADMIN_ATTENDANCE_CREATED"
    assert audit_rows[0]["attendance_id"] == row["id"]
    assert audit_rows[0]["reason"] == "WiFi outage"
    assert audit_rows[0]["performed_by"] == "admin-1"


def test_create_manual_attendance_rejected_if_already_exists(fake_client):
    settings = get_settings()
    attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_manual_attendance(
            employee_id="emp-1",
            attendance_date=attendance_service.get_office_today(settings),
            check_in_time=dtime(9, 10),
            check_out_time=None,
            reason="Duplicate attempt",
            marked_by_employee_id="admin-1",
            ip_address=None,
            settings=settings,
        )
    assert exc_info.value.status_code == 409


# -----------------------------------------------------------------------
# Attendance correction (admin)
# -----------------------------------------------------------------------

def test_update_attendance_not_found(fake_client):
    settings = get_settings()
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.update_attendance_by_id(
            attendance_id="does-not-exist",
            check_in_time=dtime(9, 0),
            check_out_time=None,
            reason="Fixing a typo",
            performed_by_employee_id="admin-1",
            ip_address=None,
            settings=settings,
        )
    assert exc_info.value.status_code == 404


def test_update_attendance_requires_reason(fake_client):
    settings = get_settings()
    row = attendance_service.create_manual_attendance(
        employee_id="emp-1",
        attendance_date=date(2026, 8, 17),
        check_in_time=dtime(9, 10),
        check_out_time=None,
        reason="Initial reason",
        marked_by_employee_id="admin-1",
        ip_address=None,
        settings=settings,
    )
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.update_attendance_by_id(
            attendance_id=row["id"],
            check_in_time=dtime(9, 5),
            check_out_time=None,
            reason="",
            performed_by_employee_id="admin-2",
            ip_address=None,
            settings=settings,
        )
    assert exc_info.value.status_code == 400


def test_update_attendance_only_changes_provided_fields(fake_client):
    settings = get_settings()
    row = attendance_service.create_manual_attendance(
        employee_id="emp-1",
        attendance_date=date(2026, 8, 17),
        check_in_time=dtime(9, 10),
        check_out_time=None,
        reason="Forgot to check in",
        marked_by_employee_id="admin-1",
        ip_address=None,
        settings=settings,
    )
    updated = attendance_service.update_attendance_by_id(
        attendance_id=row["id"],
        check_in_time=None,  # not changing check-in
        check_out_time=dtime(18, 0),  # adding check-out
        reason="Adding checkout after system restored",
        performed_by_employee_id="admin-2",
        ip_address=None,
        settings=settings,
    )
    # check-in preserved from before, check-out newly added
    assert updated["check_in"].startswith("2026-08-17T09:10")
    assert updated["check_out"].startswith("2026-08-17T18:00")


def test_update_attendance_writes_audit_log_with_old_and_new_values(fake_client):
    settings = get_settings()
    row = attendance_service.create_manual_attendance(
        employee_id="emp-1",
        attendance_date=date(2026, 8, 17),
        check_in_time=dtime(9, 10),
        check_out_time=dtime(18, 0),
        reason="Initial manual entry",
        marked_by_employee_id="admin-1",
        ip_address=None,
        settings=settings,
    )
    attendance_service.update_attendance_by_id(
        attendance_id=row["id"],
        check_in_time=dtime(9, 0),  # correcting the check-in time
        check_out_time=None,
        reason="Correcting check-in time — was recorded wrong",
        performed_by_employee_id="admin-2",
        ip_address="5.6.7.8",
        settings=settings,
    )
    audit_rows = fake_client.tables["audit_logs"].rows
    correction = [r for r in audit_rows if r["action"] == "ADMIN_ATTENDANCE_UPDATED"][0]
    assert correction["old_value"]["check_in"].startswith("2026-08-17T09:10")
    assert correction["new_value"]["check_in"].startswith("2026-08-17T09:00")
    assert correction["performed_by"] == "admin-2"
    assert correction["ip_address"] == "5.6.7.8"


def test_update_attendance_checkout_without_any_checkin_rejected(fake_client):
    settings = get_settings()
    # Create a manual row with NO check-in at all (edge case: admin marks
    # only a reason placeholder — unusual but not prevented at creation
    # since check_in_time is optional there too).
    row = attendance_service.create_manual_attendance(
        employee_id="emp-1",
        attendance_date=date(2026, 8, 17),
        check_in_time=None,
        check_out_time=None,
        reason="Placeholder pending investigation",
        marked_by_employee_id="admin-1",
        ip_address=None,
        settings=settings,
    )
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.update_attendance_by_id(
            attendance_id=row["id"],
            check_in_time=None,
            check_out_time=dtime(18, 0),
            reason="Trying to add checkout with no checkin",
            performed_by_employee_id="admin-2",
            ip_address=None,
            settings=settings,
        )
    assert exc_info.value.status_code == 400


# -----------------------------------------------------------------------
# Phase 14: laptop presence gate on check-in
# -----------------------------------------------------------------------

def test_check_in_blocked_without_laptop_presence(fake_client):
    """A brand-new employee with no laptop_presence row at all should be
    blocked from checking in via phone."""
    settings = get_settings()
    # "emp-new" was never seeded with a laptop_presence row (unlike
    # emp-1/emp-2, which the fixture seeds by default).
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in("emp-new", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert exc_info.value.status_code == 403
    assert "laptop" in exc_info.value.detail.lower()


def test_check_in_blocked_with_stale_laptop_presence(fake_client):
    """A laptop that pinged too long ago (older than
    laptop_presence_freshness_minutes) should not count as connected."""
    settings = get_settings()
    stale_time = (attendance_service.get_office_now(settings) - timedelta(minutes=30)).isoformat()
    fake_client.tables["laptop_presence"].rows.append(
        {"employee_id": "emp-stale", "last_seen_at": stale_time}
    )
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in("emp-stale", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert exc_info.value.status_code == 403
    assert "laptop" in exc_info.value.detail.lower()


def test_check_in_succeeds_with_fresh_laptop_presence(fake_client):
    """emp-1 is seeded with a fresh ping by the fixture — the default
    happy path used by every other check-in test in this file."""
    settings = get_settings()
    row = attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert row["employee_id"] == "emp-1"


def test_check_out_does_not_require_laptop_presence(fake_client):
    """Per design: only check-in gates on laptop presence — by check-out
    time, the day's activity monitoring already required genuine laptop
    use, a stronger signal than a fresh ping."""
    settings = get_settings()
    attendance_service.create_check_in("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    # Remove emp-1's laptop_presence row entirely to prove check-out
    # doesn't consult it at all.
    fake_client.tables["laptop_presence"].rows = [
        r for r in fake_client.tables["laptop_presence"].rows if r["employee_id"] != "emp-1"
    ]
    row = attendance_service.create_check_out("emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings)
    assert row["check_out"] is not None


# -----------------------------------------------------------------------
# Phase 14: static vs dynamic network mode
# -----------------------------------------------------------------------

def _set_network_mode(fake_client, mode, allowed_ips=None):
    fake_client.tables["company_settings"].rows[0]["network_mode"] = mode
    if allowed_ips is not None:
        fake_client.tables["company_settings"].rows[0]["allowed_ips"] = allowed_ips


def test_dynamic_mode_ignores_ip_entirely(fake_client):
    """Default mode (dynamic): GPS alone is sufficient, regardless of
    what IP the request appears to come from (or if it's None)."""
    settings = get_settings()
    _set_network_mode(fake_client, "dynamic")
    row = attendance_service.create_check_in(
        "emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings, client_ip="1.2.3.4"
    )
    assert row["employee_id"] == "emp-1"


def test_static_mode_requires_ip_match_even_with_valid_gps(fake_client):
    """Phase 14: in 'static' mode, valid GPS alone is NOT enough — the
    request must also come from an allowed IP."""
    settings = get_settings()
    _set_network_mode(fake_client, "static", allowed_ips=["103.42.196.118"])
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in(
            "emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings, client_ip="9.9.9.9"
        )
    assert exc_info.value.status_code == 403
    assert "company network" in exc_info.value.detail.lower()


def test_static_mode_succeeds_with_both_ip_and_gps(fake_client):
    settings = get_settings()
    _set_network_mode(fake_client, "static", allowed_ips=["103.42.196.118"])
    row = attendance_service.create_check_in(
        "emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings, client_ip="103.42.196.118"
    )
    assert row["employee_id"] == "emp-1"


def test_static_mode_rejects_good_ip_but_bad_gps(fake_client):
    """Confirms static mode is a genuine AND, not an OR: a correct IP
    does not excuse failing GPS verification."""
    settings = get_settings()
    _set_network_mode(fake_client, "static", allowed_ips=["103.42.196.118"])
    far_lat = OFFICE_LAT + 0.05
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in(
            "emp-1", far_lat, OFFICE_LON, GOOD_ACCURACY, settings, client_ip="103.42.196.118"
        )
    assert exc_info.value.status_code == 403
    assert "office area" in exc_info.value.detail.lower()


def test_static_mode_with_no_client_ip_rejected(fake_client):
    """If the caller's IP couldn't be resolved at all, static mode must
    fail closed, not treat a missing IP as automatically allowed."""
    settings = get_settings()
    _set_network_mode(fake_client, "static", allowed_ips=["103.42.196.118"])
    with pytest.raises(HTTPException) as exc_info:
        attendance_service.create_check_in(
            "emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings, client_ip=None
        )
    assert exc_info.value.status_code == 403


def test_check_in_audit_log_includes_network_mode(fake_client):
    settings = get_settings()
    _set_network_mode(fake_client, "static", allowed_ips=["103.42.196.118"])
    attendance_service.create_check_in(
        "emp-1", OFFICE_LAT, OFFICE_LON, GOOD_ACCURACY, settings, client_ip="103.42.196.118"
    )
    audit_rows = fake_client.tables["audit_logs"].rows
    assert audit_rows[0]["new_value"]["network_mode"] == "static"
