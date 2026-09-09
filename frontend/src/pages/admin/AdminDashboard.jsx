import { useEffect, useState } from "react";
import api from "../../services/api";
import StatCard from "../../components/StatCard";
import LoadingScreen from "../../components/LoadingScreen";
import Card from "../../components/Card";
import StatusBadge from "../../components/StatusBadge";
import { formatTime, formatDate, formatDuration } from "../../utils/formatters";
import { useAuth } from "../../context/AuthContext";
import AdminSelfAttendanceCard from "../../components/AdminSelfAttendanceCard";

const DETAIL_LABELS = {
  present: "Present today",
  late: "Late today",
  not_checked_in: "Not yet checked in",
  half_day: "Half day",
  manual: "Manual entries",
  missing_performance: "Missing performance",
  inactivity: "Inactivity flags",
};

export default function AdminDashboard() {
  const { employee } = useAuth();
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);
  const [selectedMetric, setSelectedMetric] = useState(null);
  const [details, setDetails] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [detailsError, setDetailsError] = useState(null);

  useEffect(() => {
    api
      .get("/admin/dashboard")
      .then((res) => setStats(res.data))
      .catch(() => setError("Couldn't load dashboard stats."));
  }, []);

  async function showDetails(metric) {
    if (selectedMetric === metric) {
      setSelectedMetric(null);
      setDetails(null);
      setDetailsError(null);
      return;
    }

    setSelectedMetric(metric);
    setDetails(null);
    setDetailsError(null);
    setDetailsLoading(true);

    try {
      const res = await api.get(`/admin/dashboard/details/${metric}`);
      setDetails(res.data);
    } catch (err) {
      setDetailsError(err?.response?.data?.detail || "Couldn't load the employee list.");
    } finally {
      setDetailsLoading(false);
    }
  }

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

      {employee?.role === "admin" && <AdminSelfAttendanceCard />}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Total employees" value={stats.total_employees} />
        <StatCard
          label="Present today"
          value={stats.present_today}
          tone="brand"
          onClick={() => showDetails("present")}
          active={selectedMetric === "present"}
        />
        <StatCard
          label="Late today"
          value={stats.late_today}
          tone="amber"
          onClick={() => showDetails("late")}
          active={selectedMetric === "late"}
        />
        <StatCard
          label="Not yet checked in"
          value={stats.absent_today}
          tone="danger"
          onClick={() => showDetails("not_checked_in")}
          active={selectedMetric === "not_checked_in"}
        />
        <StatCard
          label="Half day"
          value={stats.half_day_today}
          onClick={() => showDetails("half_day")}
          active={selectedMetric === "half_day"}
        />
        <StatCard
          label="Manual entries"
          value={stats.manual_today}
          onClick={() => showDetails("manual")}
          active={selectedMetric === "manual"}
        />
        <StatCard
          label="Missing performance"
          value={stats.missing_performance_count}
          tone="amber"
          onClick={() => showDetails("missing_performance")}
          active={selectedMetric === "missing_performance"}
        />
        <StatCard
          label="Inactivity flags"
          value={stats.inactivity_flags_count}
          tone="danger"
          onClick={() => showDetails("inactivity")}
          active={selectedMetric === "inactivity"}
        />
      </div>

      {selectedMetric && (
        <DashboardDetails
          metric={selectedMetric}
          details={details}
          loading={detailsLoading}
          error={detailsError}
        />
      )}

      <p className="text-xs text-slate-muted">
        “Not yet checked in” reflects employees with no attendance record for today — it isn’t a
        confirmed absence, since there’s no automatic end-of-day marking. Use manual attendance to
        record a confirmed absence.
      </p>
    </div>
  );
}

function DashboardDetails({ metric, details, loading, error }) {
  return (
    <Card className="!p-0 overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">{DETAIL_LABELS[metric]}</h2>
          {details?.date && (
            <p className="text-xs text-slate-muted mt-0.5">{formatDate(details.date, { withYear: true })}</p>
          )}
        </div>
        {!loading && details && (
          <span className="text-xs text-slate-muted">{details.rows.length} employee{details.rows.length === 1 ? "" : "s"}</span>
        )}
      </div>

      {loading ? (
        <div className="px-4 py-8 text-center text-sm text-slate-muted">Loading employee details…</div>
      ) : error ? (
        <div className="px-4 py-8 text-center text-sm text-danger">{error}</div>
      ) : !details?.rows?.length ? (
        <div className="px-4 py-8 text-center text-sm text-slate-muted">No employees in this category.</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm min-w-[620px]">
            <thead>
              <tr className="border-b border-border text-left text-xs text-slate-muted">
                <th className="px-4 py-3 font-medium">Employee</th>
                <th className="px-4 py-3 font-medium">Department</th>
                {metric !== "not_checked_in" && metric !== "missing_performance" && (
                  <th className="px-4 py-3 font-medium">Status</th>
                )}
                {metric !== "not_checked_in" && metric !== "missing_performance" && (
                  <th className="px-4 py-3 font-medium">Check-in</th>
                )}
                {metric === "missing_performance" && (
                  <th className="px-4 py-3 font-medium">Performance</th>
                )}
                {metric === "inactivity" && (
                  <th className="px-4 py-3 font-medium">Counted inactivity</th>
                )}
              </tr>
            </thead>
            <tbody>
              {details.rows.map((row) => (
                <tr key={row.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-medium text-ink">
                    {row.employee_name}
                    {row.employee_code && <span className="ml-2 text-xs text-slate-muted">{row.employee_code}</span>}
                  </td>
                  <td className="px-4 py-3 text-slate-muted">{row.department || "--"}</td>
                  {metric !== "not_checked_in" && metric !== "missing_performance" && (
                    <td className="px-4 py-3"><StatusBadge status={row.status} /></td>
                  )}
                  {metric !== "not_checked_in" && metric !== "missing_performance" && (
                    <td className="px-4 py-3 font-mono">{formatTime(row.check_in)}</td>
                  )}
                  {metric === "missing_performance" && (
                    <td className="px-4 py-3 text-amber">Not submitted</td>
                  )}
                  {metric === "inactivity" && (
                    <td className="px-4 py-3 font-mono">{formatDuration(row.counted_inactivity_seconds)}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
