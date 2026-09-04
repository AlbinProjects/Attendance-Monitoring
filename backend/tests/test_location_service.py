"""
Tests for app.services.location_service: Haversine distance correctness,
GPS accuracy/radius verification boundaries, and (via the Pydantic schema)
rejection of malformed client-supplied coordinates.
"""

import pytest
from pydantic import ValidationError

from app.schemas.attendance import GpsCheckInRequest
from app.services import location_service

OFFICE_LAT = 10.0234
OFFICE_LON = 76.3487
RADIUS_METERS = 100.0
MAX_ACCURACY_METERS = 100.0


def verify(lat, lon, accuracy, radius=RADIUS_METERS, max_accuracy=MAX_ACCURACY_METERS):
    return location_service.verify_location(
        lat, lon, accuracy, OFFICE_LAT, OFFICE_LON, radius, max_accuracy
    )


# -----------------------------------------------------------------------
# Haversine distance correctness
# -----------------------------------------------------------------------

def test_haversine_same_point_is_zero():
    d = location_service.haversine_distance_meters(OFFICE_LAT, OFFICE_LON, OFFICE_LAT, OFFICE_LON)
    assert d < 0.01


def test_haversine_known_distance_one_degree_latitude():
    """1 degree of latitude is ~111.32 km everywhere on Earth — a solid
    known-value check independent of the office coordinates."""
    d = location_service.haversine_distance_meters(0.0, 0.0, 1.0, 0.0)
    assert 110_500 < d < 111_700  # allow small tolerance for spherical approximation


def test_haversine_known_distance_equator_quarter():
    """0 to 90 degrees longitude along the equator is a quarter of Earth's
    circumference, ~10,007.5 km."""
    d = location_service.haversine_distance_meters(0.0, 0.0, 0.0, 90.0)
    assert 9_990_000 < d < 10_020_000


def test_haversine_symmetric():
    d1 = location_service.haversine_distance_meters(10.0, 76.0, 10.01, 76.01)
    d2 = location_service.haversine_distance_meters(10.01, 76.01, 10.0, 76.0)
    assert abs(d1 - d2) < 0.001


# -----------------------------------------------------------------------
# verify_location — radius boundary
# -----------------------------------------------------------------------

def test_verify_location_at_office_is_verified():
    result = verify(OFFICE_LAT, OFFICE_LON, 15.0)
    assert result.verified is True
    assert result.distance_meters < 1.0
    assert result.reason is None


def test_verify_location_far_away_rejected():
    result = verify(OFFICE_LAT + 0.05, OFFICE_LON, 15.0)
    assert result.verified is False
    assert result.reason == "outside_radius"
    assert result.distance_meters > RADIUS_METERS


def test_verify_location_just_inside_radius():
    nearby_lat = OFFICE_LAT + (90 / 111_320)  # ~90m north
    result = verify(nearby_lat, OFFICE_LON, 15.0)
    assert result.verified is True
    assert result.distance_meters < 100.0


def test_verify_location_just_outside_radius():
    far_lat = OFFICE_LAT + (110 / 111_320)  # ~110m north
    result = verify(far_lat, OFFICE_LON, 15.0)
    assert result.verified is False
    assert result.reason == "outside_radius"


def test_verify_location_exactly_at_radius_boundary_is_verified():
    """distance <= radius should pass (inclusive boundary, per spec
    section 5's example: 'distance <= OFFICE_GPS_RADIUS_METERS then
    location check passes')."""
    exact_lat = OFFICE_LAT + (RADIUS_METERS / 111_320)
    result = verify(exact_lat, OFFICE_LON, 15.0)
    assert result.distance_meters == pytest.approx(100.0, abs=1.0)


# -----------------------------------------------------------------------
# verify_location — GPS accuracy
# -----------------------------------------------------------------------

def test_verify_location_poor_accuracy_rejected_even_at_office():
    result = verify(OFFICE_LAT, OFFICE_LON, 150.0)
    assert result.verified is False
    assert result.reason == "accuracy_too_low"


def test_verify_location_accuracy_exactly_at_threshold_is_verified():
    result = verify(OFFICE_LAT, OFFICE_LON, MAX_ACCURACY_METERS)
    assert result.verified is True


def test_verify_location_accuracy_checked_before_radius():
    """If BOTH accuracy is poor AND the location is outside the radius,
    the accuracy failure should be reported (accuracy is checked first,
    matching spec section 10's step ordering: validate accuracy, then
    calculate/reject on distance)."""
    result = verify(OFFICE_LAT + 0.05, OFFICE_LON, 500.0)
    assert result.verified is False
    assert result.reason == "accuracy_too_low"


# -----------------------------------------------------------------------
# verify_location — different office/radius parameters per call
# -----------------------------------------------------------------------

def test_verify_location_uses_explicit_parameters_not_global_state():
    """Confirms office coordinates and thresholds are taken from the
    arguments, not any module-level/settings state — this is what makes
    per-request EffectiveConfig (Phase 14, DB-over-env) actually work."""
    other_office_lat, other_office_lon = 20.5, 78.9
    result = location_service.verify_location(
        other_office_lat, other_office_lon, 10.0, other_office_lat, other_office_lon, 50.0, 50.0
    )
    assert result.verified is True
    assert result.distance_meters < 1.0


def test_verify_location_respects_custom_radius():
    # 300m away, but with a radius widened to 500m -> passes.
    lat_300m = OFFICE_LAT + (300 / 111_320)
    result = verify(lat_300m, OFFICE_LON, 15.0, radius=500.0)
    assert result.verified is True


# -----------------------------------------------------------------------
# GpsCheckInRequest schema validation (untrusted client input)
# -----------------------------------------------------------------------

def test_schema_rejects_latitude_above_90():
    with pytest.raises(ValidationError):
        GpsCheckInRequest(latitude=91.0, longitude=0.0, accuracy=10.0)


def test_schema_rejects_latitude_below_negative_90():
    with pytest.raises(ValidationError):
        GpsCheckInRequest(latitude=-91.0, longitude=0.0, accuracy=10.0)


def test_schema_rejects_longitude_above_180():
    with pytest.raises(ValidationError):
        GpsCheckInRequest(latitude=0.0, longitude=181.0, accuracy=10.0)


def test_schema_rejects_longitude_below_negative_180():
    with pytest.raises(ValidationError):
        GpsCheckInRequest(latitude=0.0, longitude=-181.0, accuracy=10.0)


def test_schema_rejects_negative_accuracy():
    with pytest.raises(ValidationError):
        GpsCheckInRequest(latitude=10.0, longitude=76.0, accuracy=-5.0)


def test_schema_accepts_zero_accuracy():
    """accuracy=0 is a theoretically perfect reading — not realistic, but
    not invalid per se (>= 0, not > 0)."""
    req = GpsCheckInRequest(latitude=10.0, longitude=76.0, accuracy=0.0)
    assert req.accuracy == 0.0


def test_schema_accepts_boundary_latitude_values():
    GpsCheckInRequest(latitude=90.0, longitude=180.0, accuracy=10.0)
    GpsCheckInRequest(latitude=-90.0, longitude=-180.0, accuracy=10.0)


def test_schema_rejects_missing_fields():
    with pytest.raises(ValidationError):
        GpsCheckInRequest(latitude=10.0)  # missing longitude, accuracy
