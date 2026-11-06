
import { useCallback, useState } from "react";

const MAX_WAIT_MS = 20_000;
const TARGET_ACCURACY_METERS = 30;
const MIN_WAIT_MS = 3_000;

export default function useGeolocation() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const getLocation = useCallback(() => {
    setLoading(true);
    setError(null);

    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        const message = "Location services aren't available on this device.";
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

        // Keep only the most accurate reading.
        if (
          !bestPosition ||
          position.coords.accuracy < bestPosition.coords.accuracy
        ) {
          bestPosition = position;
        }

        const elapsed = Date.now() - startTime;

        // Stop early if accuracy is good enough.
        if (
          bestPosition.coords.accuracy <= TARGET_ACCURACY_METERS &&
          elapsed >= MIN_WAIT_MS
        ) {
          finish(bestPosition);
        }
      };

      const onError = (geoError) => {
        if (geoError.code === 1) {
          fail("Location permission is required for attendance.");
        }
      };

      try {
        watchId = navigator.geolocation.watchPosition(
          onSuccess,
          onError,
          {
            enableHighAccuracy: true,
            timeout: MAX_WAIT_MS,
            maximumAge: 0,
          }
        );

        // After 20 seconds, return the best available reading.
        timerId = setTimeout(() => {
          if (bestPosition) {
            finish(bestPosition);
          } else {
            fail(
              "Unable to get your location. Please enable GPS and try again."
            );
          }
        }, MAX_WAIT_MS);

      } catch (err) {
        fail("Couldn't access location services. Please try again.");
      }
    });
  }, []);

  return {
    getLocation,
    loading,
    error,
  };
}
