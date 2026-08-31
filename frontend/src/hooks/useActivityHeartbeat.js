import { useEffect, useRef } from "react";
import api from "../services/api";

const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "click", "touchstart"];
const DEFAULT_INTERVAL_MS = 45_000; // keep in sync with backend's default; see .env ACTIVITY_HEARTBEAT_INTERVAL_SECONDS

/**
 * Detects the FACT that a browser activity event occurred — never its
 * content (see backend README "What counts as activity"). No keylogging,
 * no screenshots, no history. A heartbeat is only ever sent to the backend
 * if genuine activity happened since the last one; a silent tab sends
 * nothing, letting the backend's own inactivity-period logic (Phase 6) do
 * its job.
 *
 * `enabled` should reflect "currently checked in, not yet checked out" —
 * pass false outside of an open attendance session so no heartbeats are
 * sent when there's nothing to track.
 */
export default function useActivityHeartbeat(enabled, intervalMs = DEFAULT_INTERVAL_MS) {
  const hasActivityRef = useRef(false);

  useEffect(() => {
    if (!enabled) return undefined;

    const markActive = () => {
      hasActivityRef.current = true;
    };

    ACTIVITY_EVENTS.forEach((evt) => window.addEventListener(evt, markActive, { passive: true }));

    const sendHeartbeatIfActive = () => {
      if (!hasActivityRef.current) return;
      hasActivityRef.current = false;
      api.post("/activity/heartbeat").catch(() => {
        // Heartbeats are best-effort — a missed one just means this
        // interval's activity isn't recorded; the next successful one
        // still keeps the session accurate. Never surface this to the
        // user as an error.
      });
    };

    const intervalId = setInterval(sendHeartbeatIfActive, intervalMs);

    return () => {
      ACTIVITY_EVENTS.forEach((evt) => window.removeEventListener(evt, markActive));
      clearInterval(intervalId);
    };
  }, [enabled, intervalMs]);
}
