import { useEffect, useState } from "react";
import api from "../services/api";
import Card from "../components/Card";
import StatusBadge from "../components/StatusBadge";
import LoadingScreen from "../components/LoadingScreen";
import { formatDate, formatTime, formatDuration } from "../utils/formatters";

export default function Attendance() {
  const [history, setHistory] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.get("/attendance/today"), api.get("/attendance/history")])
      .then(([todayRes, historyRes]) => {
        const today = todayRes.data;
        const rows = historyRes.data || [];
        const hasToday = rows.some((row) => row.attendance_date === today.attendance_date);
        setHistory(hasToday ? rows : [today, ...rows]);
      })
      .catch((err) => setError(err?.response?.data?.detail || "Couldn't load your attendance history."));
  }, []);

  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!history) return <LoadingScreen />;

  const months = groupByMonth(history, "attendance_date");

  return (
    <div className="space-y-5">
      <div><h1 className="text-lg font-semibold text-ink">Attendance</h1><p className="text-xs text-slate-muted mt-1">Your daily attendance records, including today.</p></div>
      {months.map(({ key, label, rows }) => (
        <section key={key}>
          <h2 className="text-sm font-semibold text-ink mb-3">{label}</h2>
          <div className="space-y-2.5">
            {rows.map((row) => (
              <Card key={`${row.id || "today"}-${row.attendance_date}`} padded className="!p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-medium text-ink">{formatDate(row.attendance_date, { withYear: true })}</p>
                  {row.status ? <StatusBadge status={row.status} /> : <span className="rounded-full bg-surface px-2.5 py-1 text-xs text-slate-muted">Not checked in</span>}
                </div>
                <div className="grid grid-cols-3 gap-3 mt-3 text-sm">
                  <div><p className="text-slate-muted text-xs">Check-in</p><p className="font-mono mt-0.5">{formatTime(row.check_in) || "—"}</p></div>
                  <div><p className="text-slate-muted text-xs">Check-out</p><p className="font-mono mt-0.5">{formatTime(row.check_out) || "—"}</p></div>
                  <div><p className="text-slate-muted text-xs">Break time</p><p className="font-mono mt-0.5">{formatDuration(row.total_break_seconds || 0)}</p></div>
                </div>
                {row.breaks?.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-border space-y-1">
                    {row.breaks.map((b) => (
                      <div key={b.id} className="flex items-center justify-between text-xs">
                        <span className="text-slate-muted">{breakLabel(b.break_type)}</span>
                        <span className="font-mono text-ink">{formatTime(b.started_at)} → {b.ended_at ? formatTime(b.ended_at) : "now"}</span>
                      </div>
                    ))}
                  </div>
                )}
                {row.status === "manual" && row.reason && <p className="text-xs text-neutral2 mt-3 bg-neutral2-tint rounded-lg px-2.5 py-1.5">Marked by admin: {row.reason}</p>}
              </Card>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function breakLabel(type) {
  return { tea: "Tea Break", lunch: "Lunch Break", evening: "Evening Break" }[type] || type;
}

function groupByMonth(rows, dateField) {
  const groups = new Map();
  for (const row of rows) {
    const value = row[dateField];
    if (!value) continue;
    const [year, month] = value.split("-");
    const key = `${year}-${month}`;
    if (!groups.has(key)) {
      const date = new Date(Number(year), Number(month) - 1, 1);
      groups.set(key, { key, label: date.toLocaleDateString(undefined, { month: "long", year: "numeric" }), rows: [] });
    }
    groups.get(key).rows.push(row);
  }
  return Array.from(groups.values()).sort((a, b) => b.key.localeCompare(a.key));
}
