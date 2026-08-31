"""
Centralized, typed application configuration.

Every environment-dependent value (GPS office location, business-rule
thresholds, Supabase credentials, CORS origins) is loaded here ONCE and
referenced everywhere else via the `get_settings()` dependency. Nothing
business-specific is hard-coded elsewhere in the codebase — see the
individual field comments for how each value is meant to be changed
without touching source code.
"""

from datetime import time
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Environment -----------------------------------------------------
    environment: str = Field(default="development")
    log_level: str = Field(default="info")

    # --- Supabase ----------------------------------------------------------
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    supabase_jwt_secret: str

    # --- Company network — informational/diagnostic only (Phase 13) --------
    # As of Phase 13, IP allowlisting is NO LONGER the attendance
    # authorization mechanism (the company's ISP uses CGNAT with a
    # dynamic public IP, so a permanent allowlist isn't viable — see
    # README "GPS-based attendance verification"). This value is now
    # OPTIONAL. If set, network_service functions remain available for
    # informational/diagnostic IP logging (e.g. on admin actions), but
    # nothing in attendance check-in/check-out depends on it, and the
    # application must start normally with this unset.
    company_allowed_ips_raw: str = Field(default="", alias="COMPANY_ALLOWED_IPS")

    # How many trusted reverse-proxy hops precede this API. Used by
    # network_service to decide which X-Forwarded-For entry to trust
    # (still relevant for informational IP capture, e.g. audit logs).
    trusted_proxy_hop_count: int = Field(default=1, alias="TRUSTED_PROXY_HOP_COUNT")

    # --- GPS attendance verification (Phase 13) -----------------------------
    # The office's coordinates are the actual source of truth for
    # attendance location verification — never hard-coded in the frontend
    # (see README "GPS-based attendance verification"). Required: without
    # these, GPS check-in/check-out cannot function, so the app fails fast
    # at startup rather than silently accepting unverifiable attendance.
    office_latitude: float = Field(alias="OFFICE_LATITUDE")
    office_longitude: float = Field(alias="OFFICE_LONGITUDE")
    # Radius, in meters, within which a check-in/check-out is considered
    # "at the office". 100m is a reasonable starting point for a single
    # building but is not universally correct — a larger campus or a
    # building with poor GPS reception may need a bigger radius.
    office_gps_radius_meters: float = Field(default=100.0, alias="OFFICE_GPS_RADIUS_METERS")
    # Reject GPS readings less precise than this (browser-reported
    # accuracy, in meters). 100m is deliberately lenient — GPS accuracy
    # degrades indoors, and being too strict would block legitimate
    # attendance from inside the office building.
    max_gps_accuracy_meters: float = Field(default=100.0, alias="MAX_GPS_ACCURACY_METERS")

    # --- Business rules ------------------------------------------------
    office_timezone: str = Field(default="Asia/Kolkata")
    office_start_time_raw: str = Field(default="09:00", alias="OFFICE_START_TIME")
    late_threshold_minutes: int = Field(default=15)
    performance_start_time_raw: str = Field(default="17:00", alias="PERFORMANCE_START_TIME")
    inactivity_start_minutes: int = Field(default=10)
    daily_inactivity_flag_minutes: int = Field(default=60)
    activity_heartbeat_interval_seconds: int = Field(default=45)

    # --- CORS ------------------------------------------------------------
    cors_allowed_origins_raw: str = Field(default="", alias="CORS_ALLOWED_ORIGINS")

    # ------------------------------------------------------------------
    # Derived / parsed properties
    # ------------------------------------------------------------------
    @property
    def company_allowed_ips(self) -> List[str]:
        return _parse_csv(self.company_allowed_ips_raw)

    @property
    def cors_allowed_origins(self) -> List[str]:
        return _parse_csv(self.cors_allowed_origins_raw)

    @property
    def office_start_time(self) -> time:
        hour, minute = self.office_start_time_raw.split(":")
        return time(int(hour), int(minute))

    @property
    def performance_start_time(self) -> time:
        hour, minute = self.performance_start_time_raw.split(":")
        return time(int(hour), int(minute))

    @field_validator("office_latitude")
    @classmethod
    def _latitude_in_range(cls, v: float) -> float:
        if not (-90 <= v <= 90):
            raise ValueError("OFFICE_LATITUDE must be between -90 and 90")
        return v

    @field_validator("office_longitude")
    @classmethod
    def _longitude_in_range(cls, v: float) -> float:
        if not (-180 <= v <= 180):
            raise ValueError("OFFICE_LONGITUDE must be between -180 and 180")
        return v

    @field_validator("office_gps_radius_meters", "max_gps_accuracy_meters")
    @classmethod
    def _positive_meters(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("GPS radius/accuracy threshold values must be positive")
        return v


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings singleton. Import and use as a FastAPI dependency:

        from app.config import get_settings
        settings = get_settings()

    Using lru_cache means the .env file is only read once per process; if you
    change environment variables at runtime in tests, call
    `get_settings.cache_clear()` first.
    """
    return Settings()
