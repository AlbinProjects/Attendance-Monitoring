import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../services/api";
import Card from "../components/Card";
import LoadingScreen from "../components/LoadingScreen";
import { formatDate, formatTime, formatDuration } from "../utils/formatters";
import { useToast } from "../context/ToastContext";

const DAY_LABELS = {
  working_day: "Working day",
  sunday: "Sunday",
  holiday: "Holiday",
  other_non_working: "Non-working day",
  leave: "Leave day",
};

const BREAK_LABELS = { tea: "Tea Break", lunch: "Lunch Break", evening: "Evening Break" };

export default function Attendance() {
  const current = new Date();
  const [year, setYear] = useState(current.getFullYear());
  const [month, setMonth] = useState(current.getMonth() + 1);
  const [days, setDays] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const { showToast } = useToast();
  const [halfDay, setHalfDay] = useState({
    leave_date: current.toISOString().slice(0, 10),
    half_day_period: "morning",
    reason: "",
  });
  const [halfDayRequesting, setHalfDayRequesting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get(`/attendance/month?year=${year}&month=${month}`);
      setDays(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(err?.response?.data?.detail || "Couldn't load your attendance history.");
    } finally {
      setLoading(false);
    }
  }, [year, month]);

  useEffect(() => { load(); }, [load]);

  const monthLabel = useMemo(
    () => new Date(year, month - 1, 1).toLocaleString(undefined, { month: "long", year: "numeric" }),
    [year, month]
  );

  const historyStartYear = 2026;
  const historyStartMonth = 9;
  const atHistoryStart = year === historyStartYear && month === historyStartMonth;

  function previousMonth() {
    if (atHistoryStart) return;
    if (month === 1) { setYear((v) => v - 1); setMonth(12); }
    else setMonth((v) => v - 1);
  }

  function nextMonth() {
    if (month === 12) { setYear((v) => v + 1); setMonth(1); }
    else setMonth((v) => v + 1);
  }

  if (loading && !days) return <LoadingScreen />;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Attendance</h1>
          <p className="text-xs text-slate-muted mt-1">Every date in the month, including calendar status, leave, breaks and daily work hours.</p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button disabled={atHistoryStart} className="rounded-lg border px-3 py-1.5 disabled:opacity-40 disabled:cursor-not-allowed" onClick={previousMonth}>‹</button>
          <span className="py-1.5 text-sm font-medium min-w-32 text-center">{monthLabel}</span>
          <button className="rounded-lg border px-3 py-1.5" onClick={nextMonth}>›</button>
        </div>
      </div>

      {error && <Card className="!border-danger/30 !bg-danger-tint"><p className="text-sm text-danger">{error}</p><button onClick={load} className="mt-2 rounded-lg border px-3 py-1.5 text-xs">Retry</button></Card>}

      <Card className="!border-amber/30 !bg-amber-50/40">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-semibold text-ink">Request Half-Day Leave</h2>
              <span className="rounded-full bg-white border border-amber/30 text-amber px-2 py-0.5 text-[10px] font-medium">Available</span>
            </div>
            <p className="text-xs text-slate-muted mt-1">Request a morning or afternoon half-day in advance. Half-day leave does not use paid or sick leave balance and requires Admin/Super Admin approval.</p>
          </div>
          <span className="rounded-full bg-amber-tint text-amber px-2.5 py-1 text-[11px] font-medium shrink-0">Half day</span>
        </div>
        <div className="grid md:grid-cols-3 gap-3 mt-3">
          <input type="date" min={new Date().toISOString().slice(0, 10)} value={halfDay.leave_date} onChange={(e) => setHalfDay((prev) => ({ ...prev, leave_date: e.target.value }))} className="rounded-xl border px-3 py-2.5 text-sm" />
          <select value={halfDay.half_day_period} onChange={(e) => setHalfDay((prev) => ({ ...prev, half_day_period: e.target.value }))} className="rounded-xl border px-3 py-2.5 text-sm">
            <option value="morning">Morning half-day</option>
            <option value="afternoon">Afternoon half-day</option>
          </select>
          <input placeholder="Reason" value={halfDay.reason} onChange={(e) => setHalfDay((prev) => ({ ...prev, reason: e.target.value }))} className="rounded-xl border px-3 py-2.5 text-sm" />
        </div>
        <div className="flex items-center justify-between gap-3 mt-3">
          <p className="text-xs text-slate-muted">Already worked 4+ net hours today? You can also request the afternoon half-day from the Check-out confirmation.</p>
          <button
            disabled={halfDayRequesting}
            onClick={async () => {
              if (!halfDay.leave_date || !halfDay.reason.trim()) {
                showToast("Select a date and enter a reason.", "error");
                return;
              }
              setHalfDayRequesting(true);
              try {
                await api.post("/calendar/leave/request", null, { params: { leave_date: halfDay.leave_date, leave_type: "half_day", half_day_period: halfDay.half_day_period, reason: halfDay.reason.trim() } });
                showToast("Half-day leave request sent for approval.");
                setHalfDay((prev) => ({ ...prev, reason: "" }));
              } catch (err) {
                showToast(err?.response?.data?.detail || "Couldn't submit half-day leave request.", "error");
              } finally {
                setHalfDayRequesting(false);
              }
            }}
            className="rounded-xl bg-ink text-white px-4 py-2.5 text-sm disabled:opacity-60 shrink-0"
          >
            {halfDayRequesting ? "Sending…" : "Ask for approval"}
          </button>
        </div>
      </Card>

      <div className="space-y-3">
        {(days || []).map((day) => <AttendanceDay key={day.date} day={day} />)}
      </div>
    </div>
  );
}

function AttendanceDay({ day }) {
  const attendance = day.attendance;
  const calendar = day.calendar || {};
  const leave = day.leave;
  const isToday = isCurrentDate(day.date);
  const leaveLabel = leave?.leave_type === "half_day"
    ? `Half-day leave${leave?.half_day_period ? ` · ${capitalize(leave.half_day_period)}` : ""}`
    : leave?.leave_type ? `${capitalize(leave.leave_type)} leave` : null;
  // An elapsed working day with no attendance is displayed as Leave. The
  // backend creates the corresponding approved unpaid-leave record after
  // the 4 PM cutoff; this fallback also keeps the history clear if a record
  // is not yet present in an older database.
  const isElapsedWorkingAbsence = calendar.is_working_day && !leave && day.work_status === "absent";
  const dayLabel = leave
    ? `Leave day · ${leaveLabel}`
    : isElapsedWorkingAbsence
      ? "Leave"
      : DAY_LABELS[day.day_status] || DAY_LABELS[calendar.day_type] || "Working day";
  const detail = leave?.leave_type === "half_day"
    ? `${capitalize(leave.half_day_period || "")} half-day${leave.reason ? ` · ${leave.reason}` : ""}`
    : calendar.name && calendar.day_type === "holiday" ? calendar.name : null;
  const workApplicable = calendar.is_working_day && !leave && !isElapsedWorkingAbsence;

  return (
    <Card className={`${isToday ? "!border-blue-200 !bg-blue-50/50" : ""} !p-4`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-ink">{formatDate(day.date, { withYear: true })}</p>
            {isToday && <span className="rounded-full bg-blue-100 text-blue-700 px-2 py-0.5 text-[10px] font-medium">Today</span>}
          </div>
          <p className={`text-xs mt-1 ${day.day_status === "holiday" ? "text-red-600" : day.day_status === "sunday" ? "text-slate-muted" : leave ? "text-amber" : "text-brand-dark"}`}>
            {dayLabel}{detail ? ` · ${detail}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {day.work_status === "checkout_missed" && (
            <span className="rounded-full bg-danger-tint text-danger px-2.5 py-1 text-xs font-medium">Check-out missed</span>
          )}
          {attendance?.status && <StatusPill status={attendance.status} />}
        </div>
      </div>

      {leave ? (
        <div className="mt-3 rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 text-sm">
          <p className="font-medium text-amber">{leave.leave_type === "half_day" ? `Half-day leave · ${capitalize(leave.half_day_period || "")}` : `${capitalize(leave.leave_type)} leave`}</p>
          {leave.reason && <p className="text-xs text-slate-muted mt-1">{leave.reason}</p>}
          {leave.reason?.startsWith("Auto-marked unpaid leave:") && <p className="text-xs text-amber mt-1">Automatically applied after the 4:00 PM no-check-in cutoff. An administrator can correct this record.</p>}
        </div>
      ) : workApplicable ? (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 text-sm">
            <Field label="Check-in" value={formatTime(attendance?.check_in) || "—"} mono />
            <Field
              label="Check-out"
              value={day.work_status === "checkout_missed" ? "Check-out missed" : (formatTime(attendance?.check_out) || "—")}
              mono
              alert={day.work_status === "checkout_missed"}
            />
            <Field label="Break time" value={formatDuration(day.total_break_seconds || 0)} mono />
            <Field label="Net work" value={day.net_work_seconds == null ? "—" : formatDuration(day.net_work_seconds)} mono />
          </div>
          <WorkTarget day={day} />
          {day.breaks?.length > 0 && <BreakDetails breaks={day.breaks} />}
        </>
      ) : isElapsedWorkingAbsence ? (
        <div className="mt-3 rounded-lg bg-amber-50 border border-amber-100 px-3 py-2 text-sm">
          <p className="font-medium text-amber">Leave</p>
          <p className="text-xs text-slate-muted mt-1">No check-in was recorded for this working day.</p>
        </div>
      ) : (
        <div className="mt-3 text-sm text-slate-muted">{calendar.day_type === "sunday" ? "No attendance required on Sunday." : calendar.day_type === "holiday" ? "No attendance required on this holiday." : "No attendance required on this non-working day."}</div>
      )}
    </Card>
  );
}

function WorkTarget({ day }) {
  const target = day.target_work_seconds || 8 * 3600;
  const actual = day.net_work_seconds;
  if (actual == null) return null;

  const completed = actual >= target;
  const percent = Math.min(100, Math.round((actual / target) * 100));
  let message = "";
  let cls = "text-slate-muted";
  if (day.work_status === "completed_8h") { message = "8-hour target completed"; cls = "text-brand-dark"; }
  else if (day.work_status === "short_8h") { message = `Short by ${formatDuration(target - actual)}`; cls = "text-danger"; }
  else if (day.work_status === "in_progress") { message = `${formatDuration(Math.max(0, target - actual))} remaining`; cls = "text-amber"; }
  else if (day.work_status === "checkout_missed") { message = "⚠ Check-out missed"; cls = "text-danger"; }

  return (
    <div className="mt-3 rounded-xl border border-border bg-surface px-3.5 py-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-muted">8-hour work completion</p>
          <p className={`text-sm font-medium mt-0.5 ${cls}`}>
            {completed ? "✓ 8 hours completed" : message}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="font-mono text-sm font-semibold text-ink">{formatDuration(actual)} / 8h</p>
          <p className={`text-[11px] ${cls}`}>{percent}%</p>
        </div>
      </div>
      <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-border">
        <div className="h-full rounded-full bg-brand transition-all" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function BreakDetails({ breaks }) {
  return (
    <div className="mt-3 pt-3 border-t border-border space-y-1.5">
      <p className="text-xs font-medium text-ink">Break details</p>
      {breaks.map((b) => <div key={b.id} className="flex items-center justify-between text-xs"><span className="text-slate-muted">{BREAK_LABELS[b.break_type] || b.break_type}</span><span className="font-mono text-ink">{formatTime(b.started_at)} → {b.ended_at ? formatTime(b.ended_at) : "In progress"}</span></div>)}
    </div>
  );
}

function Field({ label, value, mono, alert }) {
  return <div><p className="text-slate-muted text-xs">{label}</p><p className={`${mono ? "font-mono" : ""} mt-0.5 ${alert ? "text-danger font-semibold" : ""}`}>{value}</p></div>;
}

function StatusPill({ status }) {
  const map = {
    present: ["Present", "bg-brand-tint text-brand-dark"],
    late: ["Late", "bg-amber-tint text-amber"],
    manual: ["Manual entry", "bg-neutral2-tint text-neutral2"],
    half_day: ["Half day", "bg-amber-tint text-amber"],
  };
  const [label, cls] = map[status] || [status, "bg-surface text-slate-muted"];
  return <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${cls}`}>{label}</span>;
}

function capitalize(value) { return value ? value.charAt(0).toUpperCase() + value.slice(1) : value; }
function isCurrentDate(value) { const d = new Date(); const today = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`; return value === today; }
