
import { useCallback, useState } from "react";

const MAX_WAIT_MS = 8000;
const TARGET_ACCURACY_METERS = 50;
const MIN_WAIT_MS = 1000;

export default function useGeolocation() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const getLocation = useCallback(() => {
    setLoading(true);
    setError(null);

    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        const message = "Geolocation is not supported.";
        setError(message);
        setLoading(false);
        reject(new Error(message));
        return;
      }

      let watchId = null;
      let timerId = null;
      let bestPosition = null;
      let finished = false;

      const startTime = Date.now();

      const cleanup = () => {
        if (watchId !== null) {
          navigator.geolocation.clearWatch(watchId);
        }
        if (timerId !== null) {
          clearTimeout(timerId);
        }
      };

      const finish = (position) => {
        if (finished) return;

        finished = true;
        cleanup();
        setLoading(false);

        resolve({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
        });
      };

      const fail = (message) => {
        if (finished) return;

        finished = true;
        cleanup();
        setLoading(false);
        setError(message);
        reject(new Error(message));
      };

      const onSuccess = (position) => {
        if (finished) return;

        if (
          !bestPosition ||
          position.coords.accuracy < bestPosition.coords.accuracy
        ) {
          bestPosition = position;
        }

        const elapsed = Date.now() - startTime;

        if (
          bestPosition.coords.accuracy <= TARGET_ACCURACY_METERS &&
          elapsed >= MIN_WAIT_MS
        ) {
          finish(bestPosition);
        }
      };

      const onError = (geoError) => {
        if (geoError.code === 1) {
          fail("Please allow location permission.");
        }
      };

      try {
        watchId = navigator.geolocation.watchPosition(
          onSuccess,
          onError,
          {
            enableHighAccuracy: true,
            timeout: MAX_WAIT_MS,
            maximumAge: 2000,
          }
        );

        timerId = setTimeout(() => {
          if (bestPosition) {
            finish(bestPosition);
          } else {
            fail("Unable to get location. Please try again.");
          }
        }, MAX_WAIT_MS);

      } catch (err) {
        fail("Location service unavailable.");
      }
    });
  }, []);

  return { getLocation, loading, error };
}
