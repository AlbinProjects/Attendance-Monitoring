"""
Network verification service.

Two independent jobs, kept separate on purpose:

1. get_verified_client_ip() — figure out the REAL client IP from a request
   that may have passed through one or more trusted reverse proxies,
   without trusting anything a client could have injected themselves.
   Still actively used (Phase 13+) for informational/audit IP capture on
   attendance and admin actions — see app/services/attendance_service.py
   and app/routers/admin.py.
2. is_ip_allowed() / get_allowed_ips() — check that IP against the
   configured company network allowlist (IPv4/IPv6, single addresses or
   CIDR ranges).

As of Phase 13, attendance authorization no longer depends on either of
these — GPS location verification (app/services/location_service.py)
replaced public-IP allowlisting as the company's network turned out to
use CGNAT with a dynamic public IP, making a permanent allowlist
unworkable. is_ip_allowed()/get_allowed_ips() remain here, fully tested,
in case a future diagnostic or supplementary signal wants them again, but
nothing currently calls them outside their own tests.

See README "GPS-based attendance verification" for the current
attendance security model.
"""

import ipaddress
from typing import List, Optional

from fastapi import Request

from app.config import get_settings
from app.services.supabase_client import get_service_client


# -----------------------------------------------------------------------
# 1. Trusted-proxy client IP resolution
# -----------------------------------------------------------------------

def get_verified_client_ip(request: Request) -> Optional[str]:
    """
    Resolve the real client IP, trusting only as many X-Forwarded-For hops
    as TRUSTED_PROXY_HOP_COUNT says are legitimately in front of us.

    Why this matters: X-Forwarded-For is built by each proxy APPENDING the
    IP of whoever connected directly to it. A client can put anything they
    want as the header's initial content before it ever reaches the first
    proxy — e.g. sending `X-Forwarded-For: 103.42.196.118` themselves to
    try to impersonate the office network. Each trusted proxy hop after
    that appends one more, real, hard-to-fake entry (derived from the
    actual TCP connection it saw). So if there are N trusted proxies
    between the internet and this API, the last N entries in the header
    are trustworthy, and the (N)-th-from-the-right of those is the real
    client IP — everything to the left of that could be attacker-supplied.

    Example with TRUSTED_PROXY_HOP_COUNT=1 (one load balancer in front):
        Attacker sends:      X-Forwarded-For: 103.42.196.118
        Load balancer sees the attacker's real TCP connection and appends
        it:                  X-Forwarded-For: 103.42.196.118, 8.8.4.4
        We trust only the LAST entry (index -1) → 8.8.4.4. The forged
        first entry is correctly ignored.

    Example with TRUSTED_PROXY_HOP_COUNT=2 (e.g. Cloudflare -> Render LB):
        Real client 9.9.9.9 connects to Cloudflare (no forged header).
        Cloudflare appends the real client IP:  "9.9.9.9"
        Render's LB receives from Cloudflare and appends Cloudflare's own
        edge IP:                                 "9.9.9.9, 4.4.4.4"
        We trust the 2nd-from-right entry (index -2) → 9.9.9.9. Correct —
        we do NOT want Cloudflare's edge IP, we want the original client.

    If the header is missing, or has fewer entries than
    TRUSTED_PROXY_HOP_COUNT, we fail closed: return the direct TCP peer
    address (which, in a correctly configured deployment behind a proxy,
    will be the *proxy's* IP, not a company IP — so the request is
    correctly rejected downstream rather than accidentally trusted through
    a misconfiguration).
    """
    settings = get_settings()
    hop_count = settings.trusted_proxy_hop_count

    direct_peer = request.client.host if request.client else None

    if hop_count <= 0:
        # No trusted reverse proxy in front of us (e.g. a bare VPS
        # deployment with FastAPI exposed directly). The direct TCP peer
        # IS the real client. Any X-Forwarded-For header present at this
        # point is entirely client-controlled and must be ignored.
        return direct_peer

    xff = request.headers.get("x-forwarded-for")
    if not xff:
        return direct_peer

    chain = [ip.strip() for ip in xff.split(",") if ip.strip()]

    if len(chain) < hop_count:
        # Configured to expect N trusted hops but the header doesn't have
        # enough entries to safely identify one. Fail closed rather than
        # guess.
        return direct_peer

    return chain[-hop_count]


# -----------------------------------------------------------------------
# 2. IP allowlist matching
# -----------------------------------------------------------------------

def _normalize(ip: ipaddress._BaseAddress):
    """Unwrap IPv4-mapped IPv6 addresses (::ffff:103.42.196.118) so they
    compare equal to their plain IPv4 form. Some proxies/runtimes present
    IPv4 connections as this IPv6 form."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return ip.ipv4_mapped
    return ip


def is_ip_allowed(client_ip: str, allowed: List[str]) -> bool:
    """
    True if client_ip matches any entry in `allowed`, where each entry may
    be a single IPv4/IPv6 address or a CIDR range (e.g.
    "103.42.196.0/24" or "2403:a080:837:3dd1::/64").
    """
    try:
        ip = _normalize(ipaddress.ip_address(client_ip))
    except ValueError:
        return False

    for entry in allowed:
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
                if ip in network:
                    return True
            else:
                if ip == _normalize(ipaddress.ip_address(entry)):
                    return True
        except ValueError:
            # Malformed entry in configuration — skip rather than crash
            # the whole allowlist check over one bad entry.
            continue
    return False


def _get_allowed_ips_from_db() -> Optional[List[str]]:
    """
    company_settings.allowed_ips is the runtime-adjustable source of truth
    (a Super Admin can edit it from the app once Phase 8 exists). Falls
    back to None (not an empty list) on any DB error so callers know to
    use the env var default instead of wrongly blocking every employee
    company-wide due to a transient Supabase outage.
    """
    try:
        client = get_service_client()
        result = (
            client.table("company_settings")
            .select("allowed_ips")
            .eq("id", 1)
            .maybe_single()
            .execute()
        )
        if result.data and result.data.get("allowed_ips"):
            return result.data["allowed_ips"]
    except Exception:
        return None
    return None


def get_allowed_ips() -> List[str]:
    """
    Resolve the current allowlist: company_settings table takes precedence
    over the COMPANY_ALLOWED_IPS env var when present (see supabase/README.md
    "Configuration precedence").
    """
    settings = get_settings()
    db_ips = _get_allowed_ips_from_db()
    return db_ips if db_ips else settings.company_allowed_ips
