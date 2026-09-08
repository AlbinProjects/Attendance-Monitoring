"""
GPS location verification service (Phase 13, refactored in Phase 14).

Replaces public-IP allowlisting as the (sole, for dynamic-IP companies)
attendance authorization mechanism — the company's ISP uses CGNAT with a
dynamic public IPv4/IPv6, so no permanent IP allowlist is viable (see
README "GPS-based attendance verification"). This is the ONLY place
attendance location logic lives; routers and attendance_service call into
this rather than reimplementing distance math.

Client-provided latitude/longitude/accuracy are UNTRUSTED input — see
README section 25 / Phase 13 spec section 17. Range validation happens at
the Pydantic schema layer (schemas/attendance.py); this module additionally
never trusts a client-provided verification *result* (e.g. a boolean
"inside_office" flag) — the backend always independently computes
distance and re-derives verified/not-verified from the office's
configured coordinates.

Phase 14: office coordinates and thresholds are passed in explicitly
rather than read from `Settings` directly, since they can now be
overridden at runtime by a Super Admin via `company_config_service`
(DB-over-env precedence) — this function itself stays a pure, easily
testable calculation with no knowledge of where its inputs came from.

Security note (documented honestly, not oversold — see README "GPS
security limitations"): browser GPS can be spoofed on some devices,
accuracy varies especially indoors, and this does not provide absolute
proof of physical presence. It's a practical, low-cost presence signal,
not a security-critical control on its own — which is why it's combined
with authentication, server-side timestamps, database uniqueness
constraints, and audit logging, matching the same defense-in-depth
pattern used everywhere else in this system.
"""

import math
from dataclasses import dataclass
from typing import Optional

EARTH_RADIUS_METERS = 6_371_000.0


def haversine_distance_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Great-circle distance between two lat/lon points, in meters, using the
    Haversine formula. Accurate enough for office-radius-scale distances
    (tens to low-thousands of meters) — the small error introduced by
    treating the Earth as a perfect sphere is negligible at this scale.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_METERS * c


@dataclass
class LocationVerificationResult:
    verified: bool
    distance_meters: float
    accuracy_meters: float
    reason: Optional[str] = None  # "accuracy_too_low" | "outside_radius" | None


def verify_location(
    latitude: float,
    longitude: float,
    accuracy: float,
    office_latitude: float,
    office_longitude: float,
    radius_meters: float,
    max_accuracy_meters: float,
) -> LocationVerificationResult:
    """
    The single source of truth for "is this GPS reading close enough to
    the office to count as present". office_latitude/office_longitude/
    radius_meters/max_accuracy_meters are the CALLER's responsibility to
    resolve correctly (see company_config_service.get_effective_config for
    the DB-over-env precedence) — this function only ever computes from
    what it's given, never re-derives config itself. The client only ever
    supplies raw coordinates and accuracy, never a verification result.
    """
    distance = haversine_distance_meters(latitude, longitude, office_latitude, office_longitude)

    if accuracy > max_accuracy_meters:
        return LocationVerificationResult(
            verified=False,
            distance_meters=distance,
            accuracy_meters=accuracy,
            reason="accuracy_too_low",
        )

    if distance > radius_meters:
        return LocationVerificationResult(
            verified=False,
            distance_meters=distance,
            accuracy_meters=accuracy,
            reason="outside_radius",
        )

    return LocationVerificationResult(
        verified=True,
        distance_meters=distance,
        accuracy_meters=accuracy,
        reason=None,
    )
