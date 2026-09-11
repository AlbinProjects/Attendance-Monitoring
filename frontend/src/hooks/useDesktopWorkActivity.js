import { useEffect, useState } from "react";
import api from "../services/api";
import { isLikelyMobileDevice } from "../utils/deviceType";

const AGENT_URL = "http://127.0.0.1:17891";
const REFRESH_MS = 60_000;
const STATUS_MS = 20_000;

/**
 * Connects the authenticated attendance browser to the local desktop
 * activity agent. The browser gives the agent a short-lived, employee-
 * scoped token while the attendance session is open. The agent then reports
 * only privacy-safe work-activity signals (OS idle + coarse app category).
 */
export default function useDesktopWorkActivity(enabled) {
  const [status, setStatus] = useState({ supported: false, connected: false, lastHeartbeatAt: null });

  useEffect(() => {
    if (!enabled || isLikelyMobileDevice()) {
      setStatus({ supported: false, connected: false, lastHeartbeatAt: null });
      return undefined;
    }

    let cancelled = false;

    const pushSession = async () => {
      try {
        const tokenRes = await api.post("/activity/agent-token");
        const token = tokenRes.data?.token;
        const expiresIn = tokenRes.data?.expires_in || 180;
        if (!token) throw new Error("No agent token");

        const response = await fetch(`${AGENT_URL}/session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            api_base_url: import.meta.env.VITE_API_BASE_URL,
            token,
            expires_in: expiresIn,
          }),
        });
        if (!response.ok) throw new Error("Agent bridge unavailable");
        if (!cancelled) setStatus((prev) => ({ ...prev, supported: true, connected: true }));
      } catch (_) {
        if (!cancelled) setStatus((prev) => ({ ...prev, supported: true, connected: false }));
      }
    };

    const fetchStatus = async () => {
      try {
        const response = await fetch(`${AGENT_URL}/status`);
        if (!response.ok) throw new Error("status unavailable");
        const data = await response.json();
        if (!cancelled) {
          setStatus({
            supported: true,
            connected: !!data.authorized,
            lastHeartbeatAt: data.last_heartbeat_at || null,
            lastAppCategory: data.last_app_category || null,
          });
        }
      } catch (_) {
        if (!cancelled) setStatus((prev) => ({ ...prev, supported: true, connected: false }));
      }
    };

    pushSession();
    const refreshId = setInterval(pushSession, REFRESH_MS);
    const statusId = setInterval(fetchStatus, STATUS_MS);
    fetchStatus();

    return () => {
      cancelled = true;
      clearInterval(refreshId);
      clearInterval(statusId);
      fetch(`${AGENT_URL}/stop`, { method: "POST" }).catch(() => {});
    };
  }, [enabled]);

  return status;
}
