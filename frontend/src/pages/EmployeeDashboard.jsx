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
  const [onDuty, setOnDuty] = useState(null);
  const [onDutyBusy, setOnDutyBusy] = useState(false);
  const [remoteWork, setRemoteWork] = useState(null);
  const { getLocation } = useGeolocation();

  const isCheckedIn = !!today?.check_in && !today?.check_out;
  const isOtherSite = remoteWork?.work_mode === "other_site" && ["approved", "assigned", "started"].includes(remoteWork?.status);
  const isOnDuty = !!onDuty && ["approved", "started"].includes(onDuty.status);

  // Only sends heartbeats while there's an open attendance session — see
  // hooks/useActivityHeartbeat.js.
  useActivityHeartbeat(employee?.role === "employee" && isCheckedIn);

  const loadAll = useCallback(async () => {
    const [todayRes, perfRes, missingRes, historyRes, onDutyRes, remoteRes] = await Promise.all([
      api.get("/attendance/today"),
      api.get("/performance/today"),
      api.get("/performance/missing"),
      api.get("/attendance/history"),
      api.get("/calendar/on-duty/today"),
      api.get("/calendar/remote-work/today"),
    ]);
    setToday(todayRes.data);
    setOnDuty(onDutyRes.data);
    setRemoteWork(remoteRes.data);
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

  // Admin/Super Admin can manually create or correct today's attendance while
  // the employee dashboard is already open. Keep the home-page punch state
  // synchronized so a manual check-in immediately changes the button from
  // "Check in" to "Check out" without requiring a page refresh.
  useEffect(() => {
    let cancelled = false;

    const refreshTodayAttendance = async () => {
      try {
        const res = await api.get("/attendance/today", {
          params: { _ts: Date.now() },
        });
        if (!cancelled) setToday(res.data);
      } catch (_) {
        // Keep the existing state if a transient refresh fails.
      }
    };

    refreshTodayAttendance();
    const intervalId = setInterval(refreshTodayAttendance, 15_000);

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        refreshTodayAttendance();
      }
    };
    const handleFocus = () => refreshTodayAttendance();

    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("focus", handleFocus);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("focus", handleFocus);
    };
  }, []);

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
    if (today?.check_in || isOtherSite || isOnDuty) {
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
  }, [today?.check_in, isOtherSite, isOnDuty]);

  async function handleOnDuty() {
    setOnDutyBusy(true);
    try {
      if (onDuty?.status === "started") {
        const res = await api.post("/calendar/on-duty/end");
        setOnDuty(res.data);
        showToast("On Duty ended.");
      } else {
        const res = await api.post("/calendar/on-duty/start");
        setOnDuty(res.data);
        showToast("On Duty started.");
      }
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't update On Duty.", "error");
    } finally {
      setOnDutyBusy(false);
    }
  }

  async function handlePunch() {
    if (isOtherSite || isOnDuty) {
      showToast("Check-in and check-out are not required for this work mode.", "error");
      return;
    }
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
              ⚠️ {missing.length === 1 ? "You have 1 missing performance update" : `You have ${missing.length} missing performance updates`}
            </p>
            <p className="text-xs text-amber/80 mt-1">Tap to update now</p>
          </Card>
        </Link>
      )}

      {remoteWork && !today?.check_in && (remoteWork.status === "approved" || remoteWork.status === "assigned" || remoteWork.status === "started") && (
        <Card className="border-brand/30">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-muted">Work location</p>
              <p className="font-semibold text-ink mt-1">{remoteWork.work_mode === "wfh" ? "Work From Home" : "Work From Other Site"}</p>
              <p className="text-sm text-slate-muted mt-1">{remoteWork.work_mode === "other_site" ? remoteWork.site_name : "Remote work approved"}</p>
              <p className="text-xs text-slate-muted mt-1">{remoteWork.purpose}</p>
            </div>
            <StatusBadge status="approved" />
          </div>
          <p className="text-xs text-slate-muted mt-3">{remoteWork.work_mode === "wfh" ? "Work From Home requires normal check-in/check-out, phone GPS verification, laptop presence, and laptop activity monitoring. Performance updates are also required." : "Work From Other Site does not require check-in/check-out, laptop presence, or laptop activity monitoring. Performance updates are still required."}</p>
        </Card>
      )}

      {isOtherSite && !today?.check_in && (
        <Card className="border-brand/30">
          <p className="text-xs uppercase tracking-wide text-slate-muted">Work From Other Site</p>
          <p className="font-semibold text-ink mt-1">Attendance check-in/check-out not required</p>
          <p className="text-sm text-slate-muted mt-1">Laptop presence and laptop activity monitoring are not required for this assignment.</p>
          <p className="text-sm text-slate-muted mt-1">Please continue submitting your daily performance update.</p>
        </Card>
      )}

      {employee?.role === "employee" && !today?.check_in && !isOtherSite && !isOnDuty && <LaptopStatusCard connected={laptopConnected} />}

      {onDuty && (onDuty.status === "approved" || onDuty.status === "started" || onDuty.status === "completed") && !today?.check_in && (
        <Card className="border-brand/30">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-slate-muted">On Duty</p>
              <p className="font-semibold text-ink mt-1">{onDuty.status === "started" ? "On Duty in progress" : onDuty.status === "completed" ? "On Duty completed" : "Approved — ready to start"}</p>
              <p className="text-sm text-slate-muted mt-1">{onDuty.purpose}</p>
              <p className="text-xs text-slate-muted mt-1">No laptop monitoring is required during an On Duty session. Performance updates are still required.</p>
            </div>
            {onDuty.status !== "completed" && <button disabled={onDutyBusy} onClick={handleOnDuty} className="rounded-xl bg-ink text-white px-4 py-2.5 text-sm disabled:opacity-60">{onDutyBusy ? "Please wait…" : onDuty.status === "started" ? "End On Duty" : "Start On Duty"}</button>}
          </div>
          <p className="text-xs text-slate-muted mt-2">On Duty is authorized work away from the office and does not use your leave balance.</p>
        </Card>
      )}

      {!((onDuty?.status === "approved" || onDuty?.status === "started") && !today?.check_in) && !isOtherSite && <PunchCard today={today} punching={punching} statusLabel={punchStatusLabel} onPunch={handlePunch} />}

      {employee?.role === "employee" && !isOtherSite && !isOnDuty && <ActivityCard activity={activity} />}

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
