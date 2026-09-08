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


# -----------------------------------------------------------------------
# ES256 / JWKS verification — for Supabase projects migrated to the newer
# asymmetric "JWT Signing Keys" system, where tokens are NOT signed with
# SUPABASE_JWT_SECRET at all. Uses a real EC keypair, a real ES256-signed
# token, and a real public JWK — not a superficial mock — to prove the
# actual verification path works end-to-end.
# -----------------------------------------------------------------------

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwk as jose_jwk

from app.services import jwks_service


def _generate_es256_keypair():
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_jwk = jose_jwk.construct(private_pem, algorithm="ES256").public_key().to_dict()
    return private_pem, public_jwk


def _make_es256_token(private_pem, kid, sub, exp_delta=3600):
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "role": "authenticated",
        "exp": int(time.time()) + exp_delta,
    }
    return jwt.encode(payload, private_pem, algorithm="ES256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def clear_jwks_cache():
    jwks_service.clear_cache()
    yield
    jwks_service.clear_cache()


def _mock_jwks_endpoint(monkeypatch, public_jwk, kid):
    import httpx as httpx_module

    jwks_response = {"keys": [{**public_jwk, "kid": kid, "alg": "ES256", "use": "sig"}]}

    def fake_get(url, timeout=None):
        request = httpx_module.Request("GET", url)
        return httpx_module.Response(200, json=jwks_response, request=request)

    monkeypatch.setattr(jwks_service.httpx, "get", fake_get)


async def test_es256_token_verified_via_jwks(monkeypatch):
    """A Supabase project on the new JWT Signing Keys system issues
    ES256 tokens with no HS256 secret involved at all — this must
    verify successfully via the JWKS public key, exactly what a
    real migrated project's login flow produces."""
    private_pem, public_jwk = _generate_es256_keypair()
    _mock_jwks_endpoint(monkeypatch, public_jwk, "prod-key-1")
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))

    token = _make_es256_token(private_pem, "prod-key-1", ALICE_AUTH_ID)
    employee = await dependencies.get_current_employee(make_credentials(token))
    assert employee["name"] == "Alice"


async def test_es256_token_with_wrong_key_rejected(monkeypatch):
    """A token signed by a DIFFERENT private key than the one in the
    JWKS must be rejected — proves we're not accidentally accepting
    any ES256 token regardless of signature."""
    real_private_pem, real_public_jwk = _generate_es256_keypair()
    attacker_private_pem, _ = _generate_es256_keypair()
    _mock_jwks_endpoint(monkeypatch, real_public_jwk, "prod-key-1")
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))

    forged_token = _make_es256_token(attacker_private_pem, "prod-key-1", ALICE_AUTH_ID)
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(forged_token))
    assert exc_info.value.status_code == 401


async def test_es256_token_unknown_kid_rejected(monkeypatch):
    """A kid that doesn't match anything in the JWKS (e.g. an old,
    already-rotated-out key) must be rejected, not silently accepted."""
    private_pem, public_jwk = _generate_es256_keypair()
    _mock_jwks_endpoint(monkeypatch, public_jwk, "current-key")
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))

    token = _make_es256_token(private_pem, "old-rotated-out-key", ALICE_AUTH_ID)
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(token))
    assert exc_info.value.status_code == 401


async def test_es256_expired_token_rejected(monkeypatch):
    private_pem, public_jwk = _generate_es256_keypair()
    _mock_jwks_endpoint(monkeypatch, public_jwk, "prod-key-1")
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))

    expired_token = _make_es256_token(private_pem, "prod-key-1", ALICE_AUTH_ID, exp_delta=-3600)
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(expired_token))
    assert exc_info.value.status_code == 401


async def test_jwks_endpoint_unreachable_returns_401_not_500(monkeypatch):
    """If Supabase's JWKS endpoint is temporarily unreachable, the
    client should see a clean 401 ('please log in again'), never a
    raw 500 — this is a backend operational problem, but the safest
    generic response is still to ask the user to retry login."""
    import httpx as httpx_module

    def fake_get(url, timeout=None):
        raise httpx_module.ConnectError("connection refused")

    monkeypatch.setattr(jwks_service.httpx, "get", fake_get)
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))

    private_pem, _ = _generate_es256_keypair()
    token = _make_es256_token(private_pem, "some-key", ALICE_AUTH_ID)
    with pytest.raises(HTTPException) as exc_info:
        await dependencies.get_current_employee(make_credentials(token))
    assert exc_info.value.status_code == 401


async def test_es256_key_rotation_triggers_cache_refresh(monkeypatch):
    """Simulates Supabase rotating keys mid-session: the first fetch
    caches an old JWKS; a token signed with a newly-rotated key (not
    yet in our cache) should still verify, because a kid cache-miss
    triggers exactly one automatic refetch."""
    import httpx as httpx_module

    old_private_pem, old_public_jwk = _generate_es256_keypair()
    new_private_pem, new_public_jwk = _generate_es256_keypair()

    state = {"rotated": False}

    def fake_get(url, timeout=None):
        keys = (
            [{**new_public_jwk, "kid": "key-v2", "alg": "ES256", "use": "sig"}]
            if state["rotated"]
            else [{**old_public_jwk, "kid": "key-v1", "alg": "ES256", "use": "sig"}]
        )
        request = httpx_module.Request("GET", url)
        return httpx_module.Response(200, json={"keys": keys}, request=request)

    monkeypatch.setattr(jwks_service.httpx, "get", fake_get)
    monkeypatch.setattr(dependencies, "get_service_client", lambda: FakeClient([ALICE_ROW]))

    # Prime the cache with the OLD key set (simulates our cache being
    # populated before the rotation happened).
    old_token = _make_es256_token(old_private_pem, "key-v1", ALICE_AUTH_ID)
    await dependencies.get_current_employee(make_credentials(old_token))

    # Now Supabase rotates keys server-side; a new token uses "key-v2",
    # which isn't in our cache yet.
    state["rotated"] = True
    new_token = _make_es256_token(new_private_pem, "key-v2", ALICE_AUTH_ID)
    employee = await dependencies.get_current_employee(make_credentials(new_token))
    assert employee["name"] == "Alice"
