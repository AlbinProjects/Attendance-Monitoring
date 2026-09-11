import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../services/api";
import Card from "../components/Card";
import LoadingScreen from "../components/LoadingScreen";
import StatusBadge from "../components/StatusBadge";
import { formatTime, formatDuration } from "../utils/formatters";

const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];

function pad(n) { return String(n).padStart(2, "0"); }
function monthValue(year, month) { return `${year}-${pad(month)}`; }
function addMonth(year, month, delta) {
  const d = new Date(year, month - 1 + delta, 1);
  return [d.getFullYear(), d.getMonth() + 1];
}
function hours(seconds) { return seconds == null ? null : Math.round((seconds / 3600) * 10) / 10; }
function dayStatus(day) {
  const leave = day.leave;
  const remote = day.remote_work;
  if (leave) {
    if (leave.leave_type === "half_day") return `Half-day leave${leave.half_day_period ? ` · ${leave.half_day_period}` : ""}`;
    return `${String(leave.leave_type || "leave").replace("_", " ")} leave`;
  }
  if (remote?.work_mode === "other_site") return "Work From Other Site";
  if (remote?.work_mode === "wfh") {
    if (day.work_status === "checkout_missed") return "WFH · Check-out missed";
    if (day.work_status === "short_8h") return "WFH · Not completed 8h";
    if (day.attendance?.status === "late") return "WFH · Late";
    if (day.attendance) return "WFH · Present";
  }
  if (day.calendar?.day_type === "sunday") return "Sunday";
  if (day.calendar?.day_type === "holiday") return day.calendar?.name || "Holiday";
  if (!day.calendar?.is_working_day) return day.calendar?.name || "Non-working";
  if (day.work_status === "checkout_missed") return "Check-out missed";
  if (day.work_status === "short_8h") return "Not completed 8h";
  if (day.attendance?.status === "late") return "Late";
  if (day.attendance) return "Present";
  if (day.work_status === "absent") return "Missed check-in";
  if (day.work_status === "not_checked_in") return "Not checked in";
  if (day.work_status === "upcoming") return "Upcoming";
  return "—";
}
function statusTone(day) {
  const s = dayStatus(day).toLowerCase();
  if (s.includes("leave")) return "bg-amber-50 border-amber-100 text-amber";
  if (s.includes("other site") || s.includes("wfh")) return "bg-blue-50 border-blue-100 text-blue-700";
  if (s === "present") return "bg-brand-tint border-transparent text-brand-dark";
  if (s === "late") return "bg-amber-tint border-transparent text-amber";
  if (s.includes("missed") || s.includes("not completed")) return "bg-danger-tint border-transparent text-danger";
  if (s === "sunday" || s.includes("holiday") || s.includes("non-working")) return "bg-surface border-border text-slate-muted";
  return "bg-white border-border text-slate-muted";
}

export default function MonthlyAttendance() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [days, setDays] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true); setError("");
    return api.get("/attendance/month", { params: { year, month } })
      .then((res) => setDays(res.data || []))
      .catch((err) => { setDays([]); setError(err?.response?.data?.detail || "Couldn't load monthly attendance."); })
      .finally(() => setLoading(false));
  }, [year, month]);

  useEffect(() => { load(); }, [load]);

  const chartDays = useMemo(() => (days || []).filter((d) => d.net_work_seconds != null && d.work_mode !== "other_site"), [days]);
  const completed = useMemo(() => chartDays.filter((d) => (d.net_work_seconds || 0) >= 8 * 3600).length, [chartDays]);
  const short = useMemo(() => chartDays.filter((d) => (d.work_status === "short_8h" || d.work_status === "checkout_missed") && (d.net_work_seconds || 0) < 8 * 3600).length, [chartDays]);

  function changeMonth(delta) {
    const [y, m] = addMonth(year, month, delta); setYear(y); setMonth(m);
  }

  if (loading && !days) return <LoadingScreen />;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-semibold text-ink">Monthly Attendance</h1>
          <p className="text-sm text-slate-muted mt-1">Your daily attendance, work hours and status for the selected month.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => changeMonth(-1)} className="rounded-xl border border-border bg-white px-3 py-2 text-sm font-medium">← Previous</button>
          <input type="month" value={monthValue(year, month)} onChange={(e) => { const [y,m] = e.target.value.split("-").map(Number); setYear(y); setMonth(m); }} className="rounded-xl border border-border bg-white px-3 py-2 text-sm" />
          <button onClick={() => changeMonth(1)} className="rounded-xl border border-border bg-white px-3 py-2 text-sm font-medium">Next →</button>
        </div>
      </div>

      {error ? <Card><p className="text-sm text-danger">{error}</p></Card> : null}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Month" value={`${MONTHS[month - 1]} ${year}`} />
        <Metric label="8h completed" value={completed} />
        <Metric label="Days below 8h" value={short} tone={short ? "danger" : undefined} />
        <Metric label="Days shown" value={days?.length || 0} />
      </div>

      <Card>
        <div className="flex items-start justify-between gap-3 flex-wrap mb-3">
          <div>
            <h2 className="font-semibold text-ink">Work hours</h2>
            <p className="text-xs text-slate-muted mt-1">Net working time after breaks. The 8-hour reference line is shown for Office and WFH days.</p>
          </div>
        </div>
        <AttendanceLineChart days={days || []} />
      </Card>

      <Card className="!p-0 overflow-x-auto">
        <div className="px-4 pt-4 pb-3">
          <h2 className="font-semibold text-ink">Daily details</h2>
        </div>
        <table className="w-full text-sm min-w-[900px]">
          <thead><tr className="border-y border-border text-left text-xs text-slate-muted">
            <th className="px-4 py-3">Date</th><th className="px-4 py-3">Status</th><th className="px-4 py-3">Work mode</th><th className="px-4 py-3">Check-in</th><th className="px-4 py-3">Check-out</th><th className="px-4 py-3">Break</th><th className="px-4 py-3">Net work</th><th className="px-4 py-3">8h target</th>
          </tr></thead>
          <tbody>{(days || []).map((day) => {
            const isNonWork = ["sunday", "holiday", "other_non_working"].includes(day.calendar?.day_type) || day.leave || day.remote_work?.work_mode === "other_site";
            const actual = day.net_work_seconds;
            return <tr key={day.date} className="border-b border-border last:border-0">
              <td className="px-4 py-3 font-medium">{new Date(`${day.date}T00:00:00`).toLocaleDateString(undefined,{weekday:"short",day:"2-digit",month:"short"})}</td>
              <td className="px-4 py-3"><span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-medium ${statusTone(day)}`}>{dayStatus(day)}</span></td>
              <td className="px-4 py-3 text-slate-muted">{day.remote_work?.work_mode === "wfh" ? "Work From Home" : day.remote_work?.work_mode === "other_site" ? `Other Site${day.remote_work.site_name ? ` · ${day.remote_work.site_name}` : ""}` : "Office"}</td>
              <td className="px-4 py-3 font-mono">{formatTime(day.attendance?.check_in)}</td>
              <td className="px-4 py-3 font-mono">{day.work_status === "checkout_missed" ? <span className="text-danger font-semibold">Missed</span> : formatTime(day.attendance?.check_out)}</td>
              <td className="px-4 py-3 font-mono">{formatDuration(day.total_break_seconds || 0)}</td>
              <td className="px-4 py-3 font-mono">{actual == null ? "—" : formatDuration(actual)}</td>
              <td className="px-4 py-3">{isNonWork || day.work_mode === "other_site" || day.work_status === "not_required" ? "Not required" : actual == null ? "—" : actual >= 8*3600 ? <span className="text-brand-dark">Completed</span> : <span className="text-danger">Short</span>}</td>
            </tr>;
          })}</tbody>
        </table>
      </Card>
    </div>
  );
}

function AttendanceLineChart({ days }) {
  const width = 900, height = 300, left = 46, right = 18, top = 20, bottom = 38;
  const plotW = width - left - right, plotH = height - top - bottom;
  const points = days.map((d, i) => {
    if (d.net_work_seconds == null || d.work_mode === "other_site") return null;
    const value = Math.min(10, Math.max(0, d.net_work_seconds / 3600));
    const x = left + (i / Math.max(1, days.length - 1)) * plotW;
    const y = top + (1 - value / 10) * plotH;
    return { x, y, value, day: d.date.slice(8,10), d };
  });
  const segments = [];
  let current = [];
  points.forEach((p) => { if (p) current.push(p); else if (current.length) { segments.push(current); current = []; } });
  if (current.length) segments.push(current);
  const path = (seg) => seg.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");

  return <div className="w-full overflow-x-auto">
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[680px] h-[300px]" role="img" aria-label="Daily net working hours line graph">
      {[0,2,4,6,8,10].map((v) => {
        const y = top + (1 - v/10)*plotH;
        return <g key={v}><line x1={left} x2={width-right} y1={y} y2={y} stroke="currentColor" className="text-border" strokeWidth="1" /><text x={left-8} y={y+4} textAnchor="end" className="fill-slate-muted" fontSize="11">{v}h</text></g>;
      })}
      <line x1={left} x2={width-right} y1={top + (1 - 8/10)*plotH} y2={top + (1 - 8/10)*plotH} stroke="currentColor" className="text-amber" strokeDasharray="5 4" strokeWidth="1.5" />
      {segments.map((seg, i) => <path key={i} d={path(seg)} fill="none" stroke="currentColor" className="text-brand" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />)}
      {points.map((p, i) => p ? <g key={i}><circle cx={p.x} cy={p.y} r="4" fill="currentColor" className="text-brand" /><title>{p.date}: {p.value}h</title></g> : null)}
      {days.map((d, i) => (i === 0 || i === days.length - 1 || (i+1) % 5 === 0) ? <text key={d.date} x={left + (i / Math.max(1, days.length - 1))*plotW} y={height-12} textAnchor="middle" className="fill-slate-muted" fontSize="11">{d.date.slice(8,10)}</text> : null)}
      <text x={width-right} y={top + (1 - 8/10)*plotH - 7} textAnchor="end" className="fill-amber" fontSize="11">8h target</text>
    </svg>
  </div>;
}

function Metric({ label, value, tone }) { return <Card className="!p-4"><p className="text-xs text-slate-muted">{label}</p><p className={`text-lg font-semibold mt-1 ${tone === "danger" ? "text-danger" : "text-ink"}`}>{value}</p></Card>; }
