import { useCallback, useEffect, useState } from "react";
import api from "../services/api";
import { useToast } from "../context/ToastContext";
import useGeolocation from "../hooks/useGeolocation";
import PunchCard from "./PunchCard";
import BreakCard from "./BreakCard";

/**
 * Admin's own time-clock. Admins are real attendance participants, but are
 * intentionally not subject to employee laptop-presence/activity monitoring.
 * Super Admin never renders this card and is not allowed to use attendance
 * endpoints.
 */
export default function AdminSelfAttendanceCard() {
  const { showToast } = useToast();
  const { getLocation } = useGeolocation();
  const [today, setToday] = useState(null);
  const [breakData, setBreakData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [punching, setPunching] = useState(false);
  const [punchStatusLabel, setPunchStatusLabel] = useState(null);

  const load = useCallback(async () => {
    const results = await Promise.allSettled([
      api.get("/attendance/today", { params: { _ts: Date.now() } }),
      api.get("/breaks/today", { params: { _ts: Date.now() } }),
    ]);
    if (results[0]?.status === "fulfilled") setToday(results[0].value.data);
    if (results[1]?.status === "fulfilled") setBreakData(results[1].value.data);
  }, []);

  useEffect(() => {
    setLoading(true);
    load().finally(() => setLoading(false));

    const intervalId = setInterval(load, 15000);
    const handleVisibility = () => {
      if (document.visibilityState === "visible") load();
    };
    const handleFocus = () => load();
    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleFocus);
    return () => {
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleFocus);
    };
  }, [load]);

  async function handlePunch({ requestHalfDay = false } = {}) {
    setPunching(true);
    setPunchStatusLabel(today?.check_in ? "Verifying attendance…" : "Checking your office location…");
    try {
      const position = await getLocation();
      const gpsPayload = {
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy: position.accuracy,
      };

      if (!today?.check_in) {
        await api.post("/attendance/check-in", gpsPayload);
        showToast("Location verified. Your admin attendance is marked.");
      } else {
        await api.post("/attendance/check-out", gpsPayload);
        if (requestHalfDay) {
          try {
            await api.post("/calendar/leave/request-half-day", null, {
              params: { reason: "Half-day leave requested after completing at least 4 net work hours." },
            });
            showToast("Checked out. Half-day leave request sent for approval.");
          } catch (err) {
            showToast(err?.response?.data?.detail || "Checked out, but the half-day request could not be submitted.", "error");
          }
        } else {
          showToast("Location verified. Checked out successfully.");
        }
      }
      await load();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Something went wrong. Please try again.", "error");
      await load();
    } finally {
      setPunching(false);
      setPunchStatusLabel(null);
    }
  }

  if (loading) {
    return (
      <div className="rounded-2xl border border-border bg-white p-5 text-sm text-slate-muted">
        Loading your attendance…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-base font-semibold text-ink">My attendance</h2>
        <p className="text-xs text-slate-muted mt-1">
          Admin attendance is tracked like an employee's attendance. Laptop monitoring is not required for Admin accounts.
        </p>
      </div>
      <PunchCard
        today={today}
        breakData={breakData}
        punching={punching}
        statusLabel={punchStatusLabel}
        onPunch={handlePunch}
      />
      <BreakCard
        breakData={breakData}
        canStart={!!today?.check_in && !today?.check_out}
        onChanged={load}
      />
    </div>
  );
}
