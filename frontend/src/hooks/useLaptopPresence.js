/**
 * Laptop presence ping hook (Phase 14).
 *
 * While the app is open on a device that looks like a laptop/desktop
 * (not a phone — see utils/deviceType.js), this pings the backend
 * periodically so phone check-in knows the employee's laptop is
 * connected. Only pings while the tab is actually visible — a laptop
 * with the lid closed or the tab backgrounded should not count as
 * "connected".
 *
 * This is a presence signal only: no activity content, no continuous
 * location or usage tracking beyond "the app was open recently".
 */
import { useEffect } from "react";
import api from "../services/api";
import { isLikelyMobileDevice } from "../utils/deviceType";

const PING_INTERVAL_MS = 60_000;

export default function useLaptopPresence() {
  useEffect(() => {
    if (isLikelyMobileDevice()) return undefined; // phones never ping this

    const sendPing = () => {
      if (document.visibilityState !== "visible") return;
      api.post("/activity/laptop-ping").catch(() => {
        // Best-effort — a missed ping just means the next one (within
        // the freshness window) keeps presence current. Never surface
        // this as a user-facing error.
      });
    };

    sendPing(); // immediate ping on mount, then periodic
    const intervalId = setInterval(sendPing, PING_INTERVAL_MS);

    return () => clearInterval(intervalId);
  }, []);
}
