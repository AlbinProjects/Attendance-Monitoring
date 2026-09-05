import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";
import useActivityHeartbeat from "../hooks/useActivityHeartbeat";
import useGeolocation from "../hooks/useGeolocation";
import { computeMonthlySummary } from "../utils/attendanceSummary";
import Card from "../components/Card";
import PunchCard from "../components/PunchCard";
import ActivityCard from "../components/ActivityCard";
import MonthlySummaryCard from "../components/MonthlySummaryCard";
import LoadingScreen from "../components/LoadingScreen";
import StatusBadge from "../components/StatusBadge";
import LaptopStatusCard from "../components/LaptopStatusCard";

export default function EmployeeDashboard() {
  const { employee } = useAuth();
  const { showToast } = useToast();

  const [today, setToday] = useState(null);
  const [performanceToday, setPerformanceToday] = useState(null);
  const [missing, setMissing] = useState([]);
  const [monthly, setMonthly] = useState(null);
  const [activity, setActivity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [punching, setPunching] = useState(false);
  const [punchStatusLabel, setPunchStatusLabel] = useState(null);
  const [laptopConnected, setLaptopConnected] = useState(null);
  const { getLocation } = useGeolocation();

  const isCheckedIn = !!today?.check_in && !today?.check_out;

  // Only sends heartbeats while there's an open attendance session — see
  // hooks/useActivityHeartbeat.js.
  useActivityHeartbeat(isCheckedIn);

  const loadAll = useCallback(async () => {
    const [todayRes, perfRes, missingRes, historyRes] = await Promise.all([
      api.get("/attendance/today"),
      api.get("/performance/today"),
      api.get("/performance/missing"),
      api.get("/attendance/history"),
    ]);
    setToday(todayRes.data);
    setPerformanceToday(perfRes.data);
    setMissing(missingRes.data);
    const currentMonth = new Date();
    const currentYear = currentMonth.getFullYear();
    const currentMonthNumber = String(
      currentMonth.getMonth() + 1
    ).padStart(2, "0");

    const currentMonthHistory = historyRes.data.filter((row) => {
     const date = row.attendance_date || "";
     return date.startsWith(
       `${currentYear}-${currentMonthNumber}-`
     );
    });
    
    setMonthly(computeMonthlySummary(currentMonthHistory));
  }, []);

  useEffect(() => {
    setLoading(true);
    loadAll().finally(() => setLoading(false));
  }, [loadAll]);

  // Poll the activity summary every minute while checked in, so the
  // active/inactive time on screen stays roughly current without the user
  // needing to refresh.
  useEffect(() => {
    if (!isCheckedIn) {
      setActivity(null);
      return undefined;
    }
    let cancelled = false;
    const fetchActivity = () =>
      api
        .get("/activity/today")
        .then((res) => {
          if (!cancelled) setActivity(res.data);
        })
        .catch(() => {});
    fetchActivity();
    const id = setInterval(fetchActivity, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [isCheckedIn]);

  // Only matters before check-in — that's when the laptop-presence gate
  // applies. Poll so the indicator updates live once the employee opens
  // the app on their laptop, without needing to retry check-in blindly.
  useEffect(() => {
    if (today?.check_in) {
      setLaptopConnected(null);
      return undefined;
    }
    let cancelled = false;
    const fetchStatus = () =>
      api
        .get("/activity/laptop-presence")
        .then((res) => {
          if (!cancelled) setLaptopConnected(res.data.connected);
        })
        .catch(() => {});
    fetchStatus();
    const id = setInterval(fetchStatus, 30_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [today?.check_in]);

  async function handlePunch() {
    setPunching(true);
    setPunchStatusLabel("Checking your office location…");
    try {
      let position;
      try {
        position = await getLocation();
      } catch (locErr) {
        // getLocation() already produces user-facing messages for
        // permission-denied / unavailable / timeout — surface it as-is.
        showToast(locErr.message, "error");
        return;
      }

      setPunchStatusLabel("Verifying attendance…");
      const gpsPayload = {
        latitude: position.latitude,
        longitude: position.longitude,
        accuracy: position.accuracy,
      };

      if (!today?.check_in) {
        await api.post("/attendance/check-in", gpsPayload);
        showToast("Location verified. Attendance marked successfully.");
      } else {
        await api.post("/attendance/check-out", gpsPayload);
        showToast("Location verified. Checked out — have a good evening.");
      }
      const res = await api.get("/attendance/today");
      setToday(res.data);
    } catch (err) {
      showToast(
        err?.response?.data?.detail || "Something went wrong. Please try again.",
        "error"
      );
      api
        .get("/activity/laptop-presence")
        .then((res) => setLaptopConnected(res.data.connected))
        .catch(() => {});
    } finally {
      setPunching(false);
      setPunchStatusLabel(null);
    }
  }

  if (loading) return <LoadingScreen />;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-ink">
          Welcome, {employee?.name?.split(" ")[0]}
        </h1>
        <p className="text-sm text-slate-muted">
          {new Date().toLocaleDateString(undefined, {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
      </div>

      {missing.length > 0 && (
        <Link to="/employee/performance" className="block">
          <Card className="!bg-amber-tint !border-amber/30">
            <p className="text-sm font-medium text-amber">
              ⚠️{" "}
              {missing.length === 1
                ? "You have 1 missing performance update"
                : `You have ${missing.length} missing performance updates`}
            </p>
            <p className="text-xs text-amber/80 mt-1">Tap to update now</p>
          </Card>
        </Link>
      )}

      {!today?.check_in && <LaptopStatusCard connected={laptopConnected} />}

      <PunchCard today={today} punching={punching} statusLabel={punchStatusLabel} onPunch={handlePunch} />

      <ActivityCard activity={activity} />

      {monthly && <MonthlySummaryCard monthly={monthly} />}

      <Link to="/employee/performance" className="block">
        <Card className="flex items-center justify-between">
          <div>
            <p className="text-xs uppercase tracking-wide text-slate-muted">
              Today’s performance
            </p>
            <p className="text-sm text-ink mt-1">
              {performanceToday?.status === "submitted"
                ? "Already submitted"
                : performanceToday?.status === "available"
                ? "Available — not yet submitted"
                : "Available from 5:00 PM"}
            </p>
          </div>
          {performanceToday?.status && <StatusBadge status={performanceToday.status} />}
        </Card>
      </Link>
    </div>
  );
}
