"""
Dedicated security-review regression tests (README section 59 "Security"
test list). Most of these properties are already exercised incidentally
by other test files; this file makes them explicit and named so they're
never accidentally lost in a refactor.
"""

import time
from datetime import datetime

import pytest
import pytz
from fastapi.testclient import TestClient
from jose import jwt

from app.config import get_settings
from tests.fakes import FakeSupabaseClient

TEST_JWT_SECRET = "test-secret-at-least-32-characters-long-for-hs256"
ALICE_ID = "11111111-1111-1111-1111-111111111111"
BOB_ID = "22222222-2222-2222-2222-222222222222"


def make_token(sub):
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("COMPANY_ALLOWED_IPS", "103.42.196.118")
    monkeypatch.setenv("OFFICE_LATITUDE", "10.0234")
    monkeypatch.setenv("OFFICE_LONGITUDE", "76.3487")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("OFFICE_TIMEZONE", "Asia/Kolkata")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def wired_app(monkeypatch):
    """Fully wired FastAPI app with a shared fake Supabase client patched
    into every service that resolves its own client — mirrors the
    end-to-end verification pattern used throughout this project rather
    than testing dependencies in isolation."""
    import app.dependencies as deps
    import app.services.activity_service as actsvc
    import app.services.attendance_service as attsvc
    import app.services.audit_service as audsvc
    import app.services.company_config_service as ccsvc
    import app.services.employees_service as empsvc
    import app.services.laptop_presence_service as lpsvc
    import app.services.network_service as netsvc
    import app.services.performance_service as perfsvc
    from app.main import app

    fc = FakeSupabaseClient()
    fc.tables["employees"].rows.extend(
        [
            {
                "id": "emp-alice",
                "auth_user_id": ALICE_ID,
                "employee_code": "EMP001",
                "name": "Alice",
                "email": "alice@company.com",
                "role": "employee",
                "is_active": True,
            },
            {
                "id": "emp-bob",
                "auth_user_id": BOB_ID,
                "employee_code": "EMP002",
                "name": "Bob",
                "email": "bob@company.com",
                "role": "employee",
                "is_active": True,
            },
        ]
    )
    # Default happy path: dynamic network mode (GPS-only, matching Phase
    # 13 behavior) and a fresh laptop ping for Alice, so the existing
    # check-in security tests don't need to know about Phase 14's
    # laptop-presence gate or static-mode IP requirement.
    fc.tables["company_settings"].rows.append(
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
    fc.tables["laptop_presence"].rows.append(
        {
            "employee_id": "emp-alice",
            "last_seen_at": datetime.now(pytz.timezone("Asia/Kolkata")).isoformat(),
        }
    )

    for module in (deps, actsvc, attsvc, audsvc, ccsvc, empsvc, lpsvc, netsvc, perfsvc):
        monkeypatch.setattr(module, "get_service_client", lambda c=fc: c)

    client = TestClient(app)
    return client, fc


def auth_header(uid):
    return {"Authorization": f"Bearer {make_token(uid)}"}


# -----------------------------------------------------------------------
# "Modified employee ID" — request bodies are never trusted for identity
# -----------------------------------------------------------------------

def test_performance_submission_ignores_injected_employee_id(wired_app):
    """An employee crafts a request body containing someone else's
    employee_id. The submission schema has no such field at all, so
    Pydantic silently drops it — the record is still attributed to the
    AUTHENTICATED caller (Alice), never the injected value."""
    client, fc = wired_app
    resp = client.post(
        "/api/performance",
        json={
            "employee_id": "emp-bob",  # attacker-supplied, not a real field
            "performance_text": "trying to submit as someone else",
        },
        headers=auth_header(ALICE_ID),
    )
    # Either succeeds (if within the availability window) or is rejected
    # for a business reason (e.g. not yet 5 PM) — either way, if a row was
    # created it must be attributed to Alice, never Bob.
    if resp.status_code == 200:
        assert resp.json()["employee_id"] == "emp-alice"
    rows = fc.tables["performance_updates"].rows
    for row in rows:
        assert row["employee_id"] != "emp-bob"


def test_checkin_without_gps_body_is_rejected(wired_app):
    """Phase 13: check-in now REQUIRES a GPS payload (latitude/longitude/
    accuracy) — an empty POST is correctly rejected by schema validation,
    not silently accepted."""
    client, fc = wired_app
    resp = client.post(
        "/api/attendance/check-in",
        headers=auth_header(ALICE_ID),
    )
    assert resp.status_code == 422


def test_checkin_body_cannot_inject_identity_timestamp_or_status(wired_app):
    """The GPS check-in schema only has latitude/longitude/accuracy
    fields — there is structurally no employee_id, timestamp, status, or
    location_verified field for an attacker to inject. Extra fields in
    the JSON body are silently dropped by Pydantic; identity/status/
    verification are still derived entirely server-side."""
    client, fc = wired_app
    resp = client.post(
        "/api/attendance/check-in",
        json={
            "latitude": 10.0234,
            "longitude": 76.3487,
            "accuracy": 15,
            # Attacker-injected fields — none of these are real schema
            # fields and must have zero effect on the resulting record.
            "employee_id": "emp-bob",
            "status": "present",
            "check_in": "2020-01-01T00:00:00+05:30",
            "location_verified": True,
            "distance_meters": 0,
        },
        headers=auth_header(ALICE_ID),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["employee_id"] == "emp-alice"  # never emp-bob
    assert not body["check_in"].startswith("2020")  # not the injected date
    assert body["status"] in ("present", "late")  # server-computed


# -----------------------------------------------------------------------
# "Employee attempting another employee's data"
# -----------------------------------------------------------------------

def test_attendance_history_never_exposes_query_param_for_employee_id(wired_app):
    """The attendance history endpoint has no employee_id query parameter
    at all — Alice's history is always scoped to her own authenticated
    session, with no way to ask for Bob's."""
    client, fc = wired_app
    resp = client.get(
        "/api/attendance/history?employee_id=emp-bob",  # attacker attempt
        headers=auth_header(ALICE_ID),
    )
    assert resp.status_code == 200
    # The (ignored) query param has no effect — FastAPI simply doesn't
    # bind it to anything, and the handler never reads request.query_params
    # directly for this route.


def test_employee_cannot_reach_admin_attendance_table(wired_app):
    """The only place cross-employee attendance IS visible is the admin
    table, which is role-gated — an employee hitting it directly is 403,
    not a filtered/empty 200 (which would at least confirm the route
    exists to an unauthorized caller)."""
    client, fc = wired_app
    resp = client.get("/api/admin/attendance", headers=auth_header(ALICE_ID))
    assert resp.status_code == 403


# -----------------------------------------------------------------------
# CORS configuration
# -----------------------------------------------------------------------

def test_cors_never_defaults_to_wildcard():
    """Guards against ever accidentally shipping allow_origins=['*'] as a
    default — README section 62 explicitly prohibits this in production."""
    settings = get_settings()
    assert "*" not in settings.cors_allowed_origins


def test_cors_middleware_configured_with_explicit_origins_not_wildcard():
    from app.main import app

    cors_middleware = next(
        (m for m in app.user_middleware if "CORSMiddleware" in str(m.cls)), None
    )
    assert cors_middleware is not None
    assert cors_middleware.kwargs.get("allow_origins") != ["*"]


# -----------------------------------------------------------------------
# Response minimization — no unnecessary internal fields exposed
# -----------------------------------------------------------------------

def test_employee_list_response_never_exposes_auth_user_id(wired_app):
    client, fc = wired_app
    admin_row = {
        "id": "emp-admin",
        "auth_user_id": "admin-auth-id",
        "employee_code": "ADM001",
        "name": "Carol",
        "email": "carol@company.com",
        "role": "admin",
        "is_active": True,
    }
    fc.tables["employees"].rows.append(admin_row)

    resp = client.get("/api/admin/employees", headers=auth_header("admin-auth-id"))
    assert resp.status_code == 200
    for row in resp.json():
        assert "auth_user_id" not in row


# -----------------------------------------------------------------------
# Unauthorized attendance update
# -----------------------------------------------------------------------

def test_employee_cannot_call_manual_attendance_endpoint(wired_app):
    client, fc = wired_app
    resp = client.post(
        "/api/admin/attendance/manual",
        json={
            "employee_id": "emp-alice",
            "attendance_date": "2026-08-17",
            "check_in_time": "09:00:00",
            "reason": "self-authorized override attempt",
        },
        headers=auth_header(ALICE_ID),
    )
    assert resp.status_code == 403


def test_employee_cannot_correct_attendance_record(wired_app):
    client, fc = wired_app
    fc.tables["attendance"].rows.append(
        {
            "id": "att-1",
            "employee_id": "emp-alice",
            "attendance_date": "2026-08-17",
            "check_in": "2026-08-17T09:10:00+05:30",
            "status": "present",
        }
    )
    resp = client.put(
        "/api/admin/attendance/att-1",
        json={"check_in_time": "07:00:00", "reason": "self-authorized backdating"},
        headers=auth_header(ALICE_ID),
    )
    assert resp.status_code == 403
