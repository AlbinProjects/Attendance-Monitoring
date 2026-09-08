"""
Tests for app.services.jwks_service: JWKS fetching, caching, and kid
lookup. Uses httpx's real MockTransport (not a bare monkeypatch of
httpx.get) so the actual HTTP call path is exercised.
"""

import httpx
import pytest

from app.services import jwks_service

SAMPLE_JWKS = {
    "keys": [
        {"kid": "key-1", "kty": "EC", "crv": "P-256", "x": "abc", "y": "def", "alg": "ES256"},
        {"kid": "key-2", "kty": "EC", "crv": "P-256", "x": "ghi", "y": "jkl", "alg": "ES256"},
    ]
}


@pytest.fixture(autouse=True)
def clear_cache_before_and_after():
    jwks_service.clear_cache()
    yield
    jwks_service.clear_cache()


def make_mock_httpx_get(monkeypatch, response_json, status_code=200, call_counter=None):
    def fake_get(url, timeout=None):
        if call_counter is not None:
            call_counter["count"] += 1
        request = httpx.Request("GET", url)
        return httpx.Response(status_code, json=response_json, request=request)

    monkeypatch.setattr(jwks_service.httpx, "get", fake_get)


# -----------------------------------------------------------------------
# get_jwks — fetch + cache
# -----------------------------------------------------------------------

def test_fetches_keys_from_correct_jwks_url(monkeypatch):
    captured_urls = []

    def fake_get(url, timeout=None):
        captured_urls.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=SAMPLE_JWKS, request=request)

    monkeypatch.setattr(jwks_service.httpx, "get", fake_get)
    jwks_service.get_jwks("https://myproject.supabase.co")
    assert captured_urls == ["https://myproject.supabase.co/auth/v1/jwks"]


def test_strips_trailing_slash_from_supabase_url(monkeypatch):
    captured_urls = []

    def fake_get(url, timeout=None):
        captured_urls.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=SAMPLE_JWKS, request=request)

    monkeypatch.setattr(jwks_service.httpx, "get", fake_get)
    jwks_service.get_jwks("https://myproject.supabase.co/")
    assert captured_urls == ["https://myproject.supabase.co/auth/v1/jwks"]


def test_returns_keys_list_from_response(monkeypatch):
    make_mock_httpx_get(monkeypatch, SAMPLE_JWKS)
    keys = jwks_service.get_jwks("https://myproject.supabase.co")
    assert keys == SAMPLE_JWKS["keys"]


def test_second_call_within_ttl_uses_cache_not_new_request(monkeypatch):
    counter = {"count": 0}
    make_mock_httpx_get(monkeypatch, SAMPLE_JWKS, call_counter=counter)

    jwks_service.get_jwks("https://myproject.supabase.co")
    jwks_service.get_jwks("https://myproject.supabase.co")

    assert counter["count"] == 1  # only the first call actually hit the network


def test_different_supabase_url_bypasses_cache(monkeypatch):
    counter = {"count": 0}
    make_mock_httpx_get(monkeypatch, SAMPLE_JWKS, call_counter=counter)

    jwks_service.get_jwks("https://project-a.supabase.co")
    jwks_service.get_jwks("https://project-b.supabase.co")

    assert counter["count"] == 2


def test_clear_cache_forces_refetch(monkeypatch):
    counter = {"count": 0}
    make_mock_httpx_get(monkeypatch, SAMPLE_JWKS, call_counter=counter)

    jwks_service.get_jwks("https://myproject.supabase.co")
    jwks_service.clear_cache()
    jwks_service.get_jwks("https://myproject.supabase.co")

    assert counter["count"] == 2


def test_fetch_failure_raises_not_silently_swallowed(monkeypatch):
    def fake_get(url, timeout=None):
        request = httpx.Request("GET", url)
        return httpx.Response(500, json={"error": "internal"}, request=request)

    monkeypatch.setattr(jwks_service.httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError):
        jwks_service.get_jwks("https://myproject.supabase.co")


# -----------------------------------------------------------------------
# find_key_for_kid
# -----------------------------------------------------------------------

def test_find_key_for_kid_returns_matching_key():
    key = jwks_service.find_key_for_kid(SAMPLE_JWKS["keys"], "key-2")
    assert key["kid"] == "key-2"
    assert key["x"] == "ghi"


def test_find_key_for_kid_returns_none_when_not_found():
    assert jwks_service.find_key_for_kid(SAMPLE_JWKS["keys"], "nonexistent") is None


def test_find_key_for_kid_returns_none_for_none_kid():
    assert jwks_service.find_key_for_kid(SAMPLE_JWKS["keys"], None) is None


def test_find_key_for_kid_empty_keys_list():
    assert jwks_service.find_key_for_kid([], "key-1") is None
