import { useEffect, useState } from "react";
import api from "../../services/api";
import StatCard from "../../components/StatCard";
import LoadingScreen from "../../components/LoadingScreen";

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .get("/admin/dashboard")
      .then((res) => setStats(res.data))
      .catch(() => setError("Couldn't load dashboard stats."));
  }, []);

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!stats) return <LoadingScreen />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-ink">Dashboard</h1>
        <p className="text-sm text-slate-muted mt-1">
          {new Date().toLocaleDateString(undefined, {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total employees" value={stats.total_employees} />
        <StatCard label="Present today" value={stats.present_today} tone="brand" />
        <StatCard label="Late today" value={stats.late_today} tone="amber" />
        <StatCard label="Not yet checked in" value={stats.absent_today} tone="danger" />
        <StatCard label="Half day" value={stats.half_day_today} />
        <StatCard label="Manual entries" value={stats.manual_today} />
        <StatCard label="Missing performance" value={stats.missing_performance_count} tone="amber" />
        <StatCard label="Inactivity flags" value={stats.inactivity_flags_count} tone="danger" />
      </div>

      <p className="text-xs text-slate-muted">
        “Not yet checked in” reflects employees with no attendance record for today — it isn’t a
        confirmed absence, since there’s no automatic end-of-day marking. Use manual attendance to
        record a confirmed absence.
      </p>
    </div>
  );
}
