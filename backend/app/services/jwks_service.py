"""
Supabase JWKS (JSON Web Key Set) fetching and caching.

Newer Supabase projects can migrate from the legacy single-shared-secret
JWT system (HS256) to the newer JWT Signing Keys system, which signs
tokens asymmetrically (typically ES256) with a private key Supabase holds
— verification only ever needs the corresponding PUBLIC key, fetched from
this JWKS endpoint. See https://supabase.com/docs/guides/auth/signing-keys.

This module is deliberately separate from dependencies.py's token
verification logic: this only knows how to fetch/cache/look-up keys by
`kid` (key ID); it has no opinion about what to do if a key isn't found,
what algorithm to use, or how to handle a legacy HS256 token — that
routing decision lives in dependencies.py.

Cached in-process with a TTL so a normal request doesn't pay for a network
round-trip to Supabase on every single API call — only the first request
after the cache expires (or after a cache-miss on `kid`, e.g. right after
Supabase rotates keys) triggers a refetch.
"""

import time
from typing import Any, Dict, List, Optional

import httpx

_CACHE: Dict[str, Any] = {"keys": None, "fetched_at": 0.0, "url": None}
_CACHE_TTL_SECONDS = 600  # 10 minutes — Supabase key rotations are infrequent
_FETCH_TIMEOUT_SECONDS = 5.0


def _fetch_jwks(supabase_url: str) -> List[Dict[str, Any]]:
    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    response = httpx.get(jwks_url, timeout=_FETCH_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json().get("keys", [])


def get_jwks(supabase_url: str) -> List[Dict[str, Any]]:
    """Cached JWKS keys for the given Supabase project URL. Raises on
    fetch failure — the caller decides how to translate that into an
    HTTP response (see dependencies.py, which turns any failure here into
    a generic 401 rather than a 500, since a JWKS fetch problem shouldn't
    look different from "your token doesn't verify" to the client)."""
    now = time.time()
    if (
        _CACHE["keys"] is not None
        and _CACHE["url"] == supabase_url
        and (now - _CACHE["fetched_at"]) < _CACHE_TTL_SECONDS
    ):
        return _CACHE["keys"]

    keys = _fetch_jwks(supabase_url)
    _CACHE["keys"] = keys
    _CACHE["fetched_at"] = now
    _CACHE["url"] = supabase_url
    return keys


def find_key_for_kid(keys: List[Dict[str, Any]], kid: Optional[str]) -> Optional[Dict[str, Any]]:
    if not kid:
        return None
    for key in keys:
        if key.get("kid") == kid:
            return key
    return None


def clear_cache() -> None:
    """Forces the next get_jwks() call to refetch. Used both by tests and
    by dependencies.py itself as a one-time retry when a token's `kid`
    isn't found in the current cache — this handles the case where
    Supabase rotated keys since our last fetch."""
    _CACHE["keys"] = None
    _CACHE["fetched_at"] = 0.0
    _CACHE["url"] = None
