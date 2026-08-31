"""
Tests for app.dependencies: JWT verification, employee resolution, and
role-based access control.

No real Supabase or network calls happen here — get_service_client is
monkeypatched to a small in-memory fake that mimics the supabase-py v2
fluent query interface (.table().select().eq().maybe_single().execute()).
"""

import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from jose import jwt

from app import dependencies
from app.config import get_settings

TEST_JWT_SECRET = "test-secret-at-least-32-characters-long-for-hs256"
ALICE_AUTH_ID = "11111111-1111-1111-1111-111111111111"
BOB_AUTH_ID = "22222222-2222-2222-2222-222222222222"


def make_token(sub: str, exp_delta: int = 3600, secret: str = TEST_JWT_SECRET, aud: str = "authenticated") -> str:
    payload = {
        "sub": sub,
        "aud": aud,
        "role": "authenticated",
        "exp": int(time.time()) + exp_delta,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def make_credentials(token: str):
    creds = MagicMock()
    creds.credentials = token
    return creds


class FakeResult:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """Mimics client.table(...).select(...).eq(...).maybe_single().execute()"""

    def __init__(self, rows):
        self._rows = rows
        self._filters = {}

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def maybe_single(self):
        return self

    def execute(self):
        for row in self._rows:
            if all(row.get(k) == v for k, v in self._filters.items()):
                return FakeResult(row)
        return FakeResult(None)


class FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):
        return FakeQuery(self._rows)


@pytest.fixture(autouse=True)
def env_and_cache(monkeypatch):
    """Point Settings at test values and make sure the lru_cache doesn't
    leak a previous test's Settings instance across tests."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("COMPANY_ALLOWED_IPS", "103.42.196.118")
    monkeypatch.setenv("OFFICE_LATITUDE", "10.0234")
    monkeypatch.setenv("OFFICE_LONGITUDE", "76.3487")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


ALICE_ROW = {
    "id": "emp-alice",
    "auth_user_id": ALICE_AUTH_ID,
    "employee_code": "EMP001",
    "name": "Alice",
    "email": "alice@company.com",
    "role": "employee",
    "is_active": True,
}

BOB_ADMIN_ROW = {
    "id": "emp-bob",
    "auth_user_id": BOB_AUTH_ID,
    "employee_code": "ADM001",
    "name": "Bob",
    "email": "bob@company.com",
    "role": "admin",
    "is_active": True,
}


# -----------------------------------------------------------------------
# get_current_employee
# -----------------------------------------------------------------------

async def test_valid_employee_login(monkeypatch):
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))
    employee = await dependencies.get_current_employee(make_credentials(make_token(ALICE_AUTH_ID)))
    assert employee["name"] == "Alice"
    assert employee["role"] == "employee"


async def test_valid_admin_login(monkeypatch):
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([BOB_ADMIN_ROW]))
    employee = await dependencies.get_current_employee(make_credentials(make_token(BOB_AUTH_ID)))
    assert employee["name"] == "Bob"
    assert employee["role"] == "admin"


async def test_invalid_token_rejected(monkeypatch):
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials("this-is-not-a-jwt"))
    assert exc_info.value.status_code == 401


async def test_token_wrong_signing_secret_rejected(monkeypatch):
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))
    bad_token = make_token(ALICE_AUTH_ID, secret="a-completely-different-secret-value")
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(bad_token))
    assert exc_info.value.status_code == 401


async def test_expired_token_rejected(monkeypatch):
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))
    expired_token = make_token(ALICE_AUTH_ID, exp_delta=-3600)
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(expired_token))
    assert exc_info.value.status_code == 401


async def test_inactive_employee_rejected(monkeypatch):
    inactive_alice = {**ALICE_ROW, "is_active": False}
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([inactive_alice]))
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(make_token(ALICE_AUTH_ID)))
    assert exc_info.value.status_code == 403
    assert "inactive" in exc_info.value.detail.lower()


async def test_valid_auth_user_with_no_employee_row_rejected(monkeypatch):
    # A real Supabase Auth account exists (token verifies fine) but no
    # employees row was ever provisioned for it.
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([]))
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(make_token(ALICE_AUTH_ID)))
    assert exc_info.value.status_code == 403


# -----------------------------------------------------------------------
# require_role
# -----------------------------------------------------------------------

async def test_require_role_blocks_employee_from_admin_route(monkeypatch):
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))
    employee = await dependencies.get_current_employee(make_credentials(make_token(ALICE_AUTH_ID)))
    check = dependencies.require_role("admin", "super_admin")
    with pytest.raises(HTTPException) as exc_info:
        await check(employee)
    assert exc_info.value.status_code == 403


async def test_require_role_allows_matching_admin_role(monkeypatch):
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([BOB_ADMIN_ROW]))
    employee = await dependencies.get_current_employee(make_credentials(make_token(BOB_AUTH_ID)))
    check = dependencies.require_role("admin", "super_admin")
    result = await check(employee)
    assert result["role"] == "admin"


async def test_require_role_blocks_inactive_admin(monkeypatch):
    # Even an admin-role account must be active — role check happens after
    # the is_active check inside get_current_employee, so this is exercised
    # at that layer, not require_role itself. Included here as an explicit
    # end-to-end case since it's one of the required test scenarios.
    inactive_admin = {**BOB_ADMIN_ROW, "is_active": False}
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([inactive_admin]))
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(make_token(BOB_AUTH_ID)))
    assert exc_info.value.status_code == 403
