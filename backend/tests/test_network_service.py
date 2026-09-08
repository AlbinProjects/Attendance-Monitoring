"""
Tests for app.services.network_service — the trusted-proxy IP resolution
and IP allowlist matching that gates attendance check-in/check-out.

These specifically target the attack described in README: a client sending
`X-Forwarded-For: 103.42.196.118` themselves to try to impersonate the
office network.
"""

from unittest.mock import MagicMock

import pytest

from app.config import get_settings
from app.services import network_service


def make_request(headers: dict, direct_peer: str = "10.0.0.5"):
    request = MagicMock()
    request.headers = {k.lower(): v for k, v in headers.items()}
    request.client = MagicMock(host=direct_peer)
    return request


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


def set_hop_count(monkeypatch, n: int):
    monkeypatch.setenv("TRUSTED_PROXY_HOP_COUNT", str(n))
    get_settings.cache_clear()


# -----------------------------------------------------------------------
# get_verified_client_ip
# -----------------------------------------------------------------------

def test_no_trusted_proxy_uses_direct_peer_and_ignores_forged_header(monkeypatch):
    """hop_count=0: no reverse proxy in front of us. Any XFF header must
    be completely ignored — it's 100% attacker-controlled."""
    set_hop_count(monkeypatch, 0)
    request = make_request(
        {"x-forwarded-for": "103.42.196.118"},  # attacker's forgery attempt
        direct_peer="8.8.4.4",
    )
    ip = network_service.get_verified_client_ip(request)
    assert ip == "8.8.4.4"


def test_single_trusted_proxy_ignores_forged_prefix(monkeypatch):
    """hop_count=1: header is 'forged, real_client_ip' — a single trusted
    proxy appended the real client IP after receiving the attacker's
    already-forged header. We must trust only the LAST entry."""
    set_hop_count(monkeypatch, 1)
    request = make_request(
        {"x-forwarded-for": "103.42.196.118, 9.9.9.9"},
        direct_peer="4.4.4.4",  # the proxy's own IP, as seen directly by us
    )
    ip = network_service.get_verified_client_ip(request)
    assert ip == "9.9.9.9"


def test_single_trusted_proxy_no_forgery(monkeypatch):
    """hop_count=1, legitimate case: real client goes straight through the
    one trusted proxy with no forged prefix."""
    set_hop_count(monkeypatch, 1)
    request = make_request({"x-forwarded-for": "103.42.196.118"})
    ip = network_service.get_verified_client_ip(request)
    assert ip == "103.42.196.118"


def test_two_trusted_proxies_picks_correct_hop(monkeypatch):
    """hop_count=2 (e.g. Cloudflare -> Render LB). Chain =
    [forged?, real_client_ip, edge_proxy_ip]. We want the 2nd-from-right
    entry (real_client_ip), not the edge proxy's own IP."""
    set_hop_count(monkeypatch, 2)
    request = make_request(
        {"x-forwarded-for": "1.1.1.1, 9.9.9.9, 4.4.4.4"},
    )
    ip = network_service.get_verified_client_ip(request)
    assert ip == "9.9.9.9"


def test_missing_header_fails_closed_to_direct_peer(monkeypatch):
    """hop_count>0 but no XFF header arrived at all — misconfiguration or
    a direct hit bypassing the expected proxy. Fail closed."""
    set_hop_count(monkeypatch, 1)
    request = make_request({}, direct_peer="4.4.4.4")
    ip = network_service.get_verified_client_ip(request)
    assert ip == "4.4.4.4"


def test_insufficient_chain_length_fails_closed(monkeypatch):
    """hop_count=2 but header only has 1 entry — not enough to safely
    identify the trusted hop. Fail closed rather than guess."""
    set_hop_count(monkeypatch, 2)
    request = make_request({"x-forwarded-for": "9.9.9.9"}, direct_peer="4.4.4.4")
    ip = network_service.get_verified_client_ip(request)
    assert ip == "4.4.4.4"  # NOT "9.9.9.9" — that would trust an unverified entry


def test_attacker_cannot_spoof_office_ip_with_single_trusted_proxy(monkeypatch):
    """End-to-end version of the exact attack the README calls out: an
    attacker sends X-Forwarded-For: 103.42.196.118 hoping to be treated as
    the office. With a correctly configured trusted proxy in front, the
    resolved IP must be the attacker's real IP, not the forged one."""
    set_hop_count(monkeypatch, 1)
    request = make_request(
        {"x-forwarded-for": "103.42.196.118"},  # attacker's own forged header
    )
    # The proxy in front of us appends the attacker's real IP after their
    # forged content, producing this final header as WE receive it:
    request = make_request({"x-forwarded-for": "103.42.196.118, 66.66.66.66"})
    ip = network_service.get_verified_client_ip(request)
    allowed = network_service.is_ip_allowed(ip, ["103.42.196.118"])
    assert ip == "66.66.66.66"
    assert allowed is False


# -----------------------------------------------------------------------
# is_ip_allowed
# -----------------------------------------------------------------------

def test_exact_ipv4_match():
    assert network_service.is_ip_allowed("103.42.196.118", ["103.42.196.118"]) is True


def test_ipv4_mismatch():
    assert network_service.is_ip_allowed("103.42.196.119", ["103.42.196.118"]) is False


def test_ipv4_cidr_match():
    assert network_service.is_ip_allowed("103.42.196.200", ["103.42.196.0/24"]) is True


def test_ipv4_cidr_mismatch():
    assert network_service.is_ip_allowed("103.42.197.1", ["103.42.196.0/24"]) is False


def test_ipv6_exact_match():
    ip = "2403:a080:837:3dd1:5c23:6633:b2e:5590"
    assert network_service.is_ip_allowed(ip, [ip]) is True


def test_ipv6_cidr_match():
    assert network_service.is_ip_allowed(
        "2403:a080:837:3dd1:1234:5678:9abc:def0",
        ["2403:a080:837:3dd1::/64"],
    ) is True


def test_ipv6_cidr_mismatch():
    assert network_service.is_ip_allowed(
        "2403:a080:837:9999:1234:5678:9abc:def0",
        ["2403:a080:837:3dd1::/64"],
    ) is False


def test_multiple_allowed_ips_matches_any():
    allowed = ["103.42.196.118", "45.45.45.45"]
    assert network_service.is_ip_allowed("45.45.45.45", allowed) is True
    assert network_service.is_ip_allowed("103.42.196.118", allowed) is True
    assert network_service.is_ip_allowed("1.2.3.4", allowed) is False


def test_malformed_client_ip_rejected():
    assert network_service.is_ip_allowed("not-an-ip", ["103.42.196.118"]) is False


def test_malformed_allowlist_entry_skipped_not_crashed():
    # One bad entry in config shouldn't take down the whole allowlist check.
    assert network_service.is_ip_allowed(
        "103.42.196.118", ["not-an-ip-or-cidr", "103.42.196.118"]
    ) is True


def test_ipv4_mapped_ipv6_normalizes_to_ipv4():
    # Some proxies/runtimes represent an IPv4 connection as ::ffff:a.b.c.d
    assert network_service.is_ip_allowed(
        "::ffff:103.42.196.118", ["103.42.196.118"]
    ) is True


# -----------------------------------------------------------------------
# get_allowed_ips — env fallback vs DB precedence
# -----------------------------------------------------------------------

def test_get_allowed_ips_falls_back_to_env_when_db_unavailable(monkeypatch):
    monkeypatch.setattr(network_service, "_get_allowed_ips_from_db", lambda: None)
    assert network_service.get_allowed_ips() == ["103.42.196.118"]


def test_get_allowed_ips_prefers_db_when_present(monkeypatch):
    monkeypatch.setattr(
        network_service, "_get_allowed_ips_from_db", lambda: ["9.9.9.9", "8.8.8.8"]
    )
    assert network_service.get_allowed_ips() == ["9.9.9.9", "8.8.8.8"]
