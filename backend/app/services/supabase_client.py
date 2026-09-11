"""
Supabase client factory.

This module is the single place in the backend that constructs a Supabase
client using the SERVICE ROLE key. That key bypasses Row Level Security
entirely, so every query made through this client must have its
authorization decided in Python (via get_current_employee / require_role in
app/dependencies.py) BEFORE the query runs — RLS is not there to save us
here, unlike calls the frontend might make directly with the anon key.

Never import this in the frontend. Never log the client or its config.
"""

from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


@lru_cache
def get_service_client() -> Client:
    """
    Cached singleton Supabase client authenticated with the service role
    key. Use this for all backend reads/writes that need to bypass RLS
    (e.g. looking up an employee by auth_user_id during authentication,
    before we even know their role).
    """
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
