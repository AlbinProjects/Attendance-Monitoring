/**
 * One-shot GPS location hook for attendance verification (Phase 13).
 *
 * Deliberately NOT a continuous location tracker — getCurrentPosition()
 * is called exactly once per invocation of getLocation(), only when the
 * caller actually needs a reading (e.g. the moment CHECK IN is pressed).
 * No location history is stored anywhere on the client; whatever the
 * caller does with a single returned coordinate is up to them, and this
 * hook holds no watch/subscription open in the background.
 *
 * This hook does not decide whether a location is "close enough" to the
 * office — that determination is made server-side (see backend
 * app/services/location_service.py). The frontend only requests a
 * reading and reports permission/availability problems.
 */
import { useCallback, useState } from "react";

const DEFAULT_TIMEOUT_MS = 15_000;

/**
 * @returns {{
 *   getLocation: () => Promise<{latitude: number, longitude: number, accuracy: number}>,
 *   loading: boolean,
 *   error: string | null,
 * }}
 */
export default function useGeolocation() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const getLocation = useCallback(() => {
    setLoading(true);
    setError(null);

    return new Promise((resolve, reject) => {
      if (!("geolocation" in navigator)) {
        const message = "Location services aren't available on this device.";
        setError(message);
        setLoading(false);
        reject(new Error(message));
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (position) => {
          setLoading(false);
          resolve({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy,
          });
        },
        (geoError) => {
          setLoading(false);
          const message = mapGeolocationError(geoError);
          setError(message);
          reject(new Error(message));
        },
        {
          enableHighAccuracy: true,
          timeout: DEFAULT_TIMEOUT_MS,
          maximumAge: 0, // never reuse a cached/stale position for attendance
        }
      );
    });
  }, []);

  return { getLocation, loading, error };
}

function mapGeolocationError(geoError) {
  switch (geoError.code) {
    case geoError.PERMISSION_DENIED:
      return "Location permission is required for attendance.";
    case geoError.POSITION_UNAVAILABLE:
      return "Your location couldn't be determined. Please try again.";
    case geoError.TIMEOUT:
      return "Getting your location took too long. Please try again.";
    default:
      return "Couldn't get your location. Please try again.";
  }
}
