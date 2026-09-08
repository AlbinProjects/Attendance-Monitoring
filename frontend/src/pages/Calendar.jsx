import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../services/api";
import Card from "../components/Card";
import LoadingScreen from "../components/LoadingScreen";
import { formatDate } from "../utils/formatters";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../context/ToastContext";

const STATUS_LABEL = {
  pending: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
  cancelled: "Cancelled",
};

export default function Calendar() {
  const { employee } = useAuth();
  const { showToast } = useToast();
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [days, setDays] = useState(null);
  const [leaves, setLeaves] = useState([]);
  const [balance, setBalance] = useState(null);
  const [request, setRequest] = useState({
    leave_date: "",
    leave_type: "paid",
    reason: "",
  });
  const [requesting, setRequesting] = useState(false);
  const [onDuty, setOnDuty] = useState({ on_duty_date: "", purpose: "", planned_start: "", planned_end: "" });
  const [onDutyRequests, setOnDutyRequests] = useState([]);
  const [onDutyRequesting, setOnDutyRequesting] = useState(false);
  const [remoteWork, setRemoteWork] = useState({ work_mode: "wfh", work_date: "", purpose: "", site_name: "", planned_start: "", planned_end: "" });
  const [remoteRequests, setRemoteRequests] = useState([]);
  const [remoteRequesting, setRemoteRequesting] = useState(false);

  const load = useCallback(async () => {
    const [calendarRes, leaveRes, balanceRes, onDutyRes, remoteRes] = await Promise.all([
      api.get(`/calendar/month?year=${year}&month=${month}`),
      api.get("/calendar/leave"),
      api.get("/calendar/leave/balance"),
      api.get("/calendar/on-duty"),
      api.get("/calendar/remote-work"),
    ]);
    setDays(calendarRes.data);
    setLeaves(leaveRes.data);
    setBalance(balanceRes.data);
    setOnDutyRequests(onDutyRes.data);
    setRemoteRequests(remoteRes.data);
  }, [year, month]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  const leaveByDate = useMemo(
    () => Object.fromEntries(leaves.filter((x) => x.status === "approved").map((x) => [x.leave_date, x])),
    [leaves]
  );

  const selectedDay = useMemo(
    () => days?.find((d) => d.calendar_date === request.leave_date),
    [days, request.leave_date]
  );

  async function submitRequest() {
    if (!request.leave_date || !request.reason.trim()) {
      showToast("Select a date and enter a reason.", "error");
      return;
    }
    if (selectedDay && !selectedDay.is_working_day) {
      showToast("Leave cannot be requested for a company non-working day.", "error");
      return;
    }
    setRequesting(true);
    try {
      await api.post("/calendar/leave/request", null, {
        params: request,
      });
      showToast("Leave request sent for approval.");
      setRequest((prev) => ({ ...prev, reason: "" }));
      await load();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't submit leave request.", "error");
    } finally {
      setRequesting(false);
    }
  }

  async function submitRemoteWork() {
    if (!remoteWork.work_date || !remoteWork.purpose.trim()) {
      showToast("Select a date and enter a purpose.", "error"); return;
    }
    if (remoteWork.work_mode === "other_site" && !remoteWork.site_name.trim()) {
      showToast("Enter the other work site's name/location.", "error"); return;
    }
    const selected = days.find((d) => d.calendar_date === remoteWork.work_date);
    if (selected && !selected.is_working_day) { showToast("Remote work cannot be requested for a company non-working day.", "error"); return; }
    setRemoteRequesting(true);
    try {
      await api.post("/calendar/remote-work/request", null, { params: remoteWork });
      showToast("Remote work request sent for approval.");
      setRemoteWork((prev) => ({ ...prev, purpose: "", site_name: "", planned_start: "", planned_end: "" }));
      await load();
    } catch (err) { showToast(err?.response?.data?.detail || "Couldn't submit remote work request.", "error"); }
    finally { setRemoteRequesting(false); }
  }

  async function submitOnDuty() {
    if (!onDuty.on_duty_date || !onDuty.purpose.trim()) {
      showToast("Select a date and enter the On Duty purpose.", "error");
      return;
    }
    const selected = days.find((d) => d.calendar_date === onDuty.on_duty_date);
    if (selected && !selected.is_working_day) {
      showToast("On Duty cannot be requested for a company non-working day.", "error");
      return;
    }
    if (onDuty.planned_end && !onDuty.planned_start) {
      showToast("Planned end time requires a planned start time.", "error");
      return;
    }
    setOnDutyRequesting(true);
    try {
      await api.post("/calendar/on-duty/request", null, { params: onDuty });
      showToast("On Duty request sent for approval.");
      setOnDuty((prev) => ({ ...prev, purpose: "", planned_start: "", planned_end: "" }));
      await load();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't submit On Duty request.", "error");
    } finally {
      setOnDutyRequesting(false);
    }
  }

  async function editRemoteWork(item) {
    if (!['pending', 'approved', 'assigned'].includes(item.status)) return;
    const work_mode = window.prompt("Type: wfh or other_site", item.work_mode);
    if (!work_mode || !['wfh','other_site'].includes(work_mode)) return;
    const work_date = window.prompt("Date (YYYY-MM-DD)", item.work_date);
    if (!work_date) return;
    const purpose = window.prompt("Reason / purpose", item.purpose || "");
    if (!purpose) return;
    const site_name = work_mode === 'other_site' ? (window.prompt("Site name / location", item.site_name || "") || "") : "";
    const planned_start = window.prompt("Start time (HH:MM, optional)", item.planned_start || "") || "";
    const planned_end = window.prompt("End time (HH:MM, optional)", item.planned_end || "") || "";
    try {
      await api.put(`/calendar/remote-work/${item.id}`, null, { params: { work_mode, work_date, purpose, site_name, planned_start, planned_end } });
      showToast(item.status === 'approved' && employee?.id === item.employee_id ? "Your approved request was changed and returned to Pending approval." : "Remote work updated.");
      await load();
    } catch (err) { showToast(err?.response?.data?.detail || "Couldn't update remote work.", "error"); }
  }

  async function cancelRemoteWork(id) {
    if (!window.confirm("Cancel this remote work request/assignment?")) return;
    try { await api.delete(`/calendar/remote-work/${id}`); showToast("Remote work cancelled."); await load(); }
    catch (err) { showToast(err?.response?.data?.detail || "Couldn't cancel remote work.", "error"); }
  }

  if (!days || !balance) return <LoadingScreen />;

  const leadingEmpty = new Date(year, month - 1, 1).getDay();

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-ink">Company Calendar</h1>
        <div className="flex gap-2">
          <button className="rounded-lg border px-3 py-1.5" onClick={() => { if (month === 1) { setYear(year - 1); setMonth(12); } else setMonth(month - 1); }}>‹</button>
          <span className="py-1.5 text-sm font-medium min-w-28 text-center">{new Date(year, month - 1, 1).toLocaleString(undefined, { month: "long", year: "numeric" })}</span>
          <button className="rounded-lg border px-3 py-1.5" onClick={() => { if (month === 12) { setYear(year + 1); setMonth(1); } else setMonth(month + 1); }}>›</button>
        </div>
      </div>

      <Card>
        <div className="grid grid-cols-7 gap-1 text-center text-xs text-slate-muted mb-2">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((x) => <div key={x}>{x}</div>)}
        </div>
        <div className="grid grid-cols-7 gap-1">
          {Array.from({ length: leadingEmpty }).map((_, i) => <div key={`empty-${i}`} />)}
          {days.map((d) => {
            const leave = leaveByDate[d.calendar_date];
            const isSelected = request.leave_date === d.calendar_date;
            const today = new Date();
            const todayDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
            const isToday = d.calendar_date === todayDate;
            const isHoliday = d.day_type === "holiday";
            return (
              <button
                type="button"
                key={d.calendar_date}
                onClick={() => d.is_working_day && setRequest((prev) => ({ ...prev, leave_date: d.calendar_date }))}
                className={`min-h-16 rounded-lg border p-1.5 text-left ${isHoliday ? "bg-red-50 border-red-200" : isToday ? "bg-blue-50 border-blue-200" : d.is_working_day ? "bg-white hover:border-brand" : "bg-slate-50 cursor-default"} ${isToday ? "ring-1 ring-blue-300" : ""} ${isSelected ? "ring-2 ring-brand" : ""}`}
              >
                <div className="text-xs font-medium">{Number(d.calendar_date.slice(-2))}</div>
                <div className="text-[10px] mt-1 truncate">
                  {leave ? `${leave.leave_type} leave` : d.is_working_day ? "Working" : (d.name || d.day_type.replaceAll("_", " "))}
                </div>
              </button>
            );
          })}
        </div>
        <p className="text-xs text-slate-muted mt-3">Tap a working day to select it for a leave request.</p>
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">Request leave</h2>
        <div className="grid md:grid-cols-3 gap-3">
          <input type="date" value={request.leave_date} onChange={(e) => setRequest({ ...request, leave_date: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
          <select value={request.leave_type} onChange={(e) => setRequest({ ...request, leave_type: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm">
            <option value="paid">Paid leave</option>
            <option value="sick">Sick leave</option>
          </select>
          <input placeholder="Reason" value={request.reason} onChange={(e) => setRequest({ ...request, reason: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
        </div>
        <div className="flex items-center justify-between gap-3 mt-3">
          <p className="text-xs text-slate-muted">Your request will remain pending until an authorised Admin or Super Admin approves it.</p>
          <button disabled={requesting} onClick={submitRequest} className="rounded-xl bg-ink text-white px-4 py-2.5 text-sm disabled:opacity-60">
            {requesting ? "Sending…" : "Ask for approval"}
          </button>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">Request On Duty</h2>
        <div className="grid md:grid-cols-5 gap-3">
          <input type="date" value={onDuty.on_duty_date} onChange={(e) => setOnDuty({ ...onDuty, on_duty_date: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
          <input placeholder="Purpose (client meeting, field work…)" value={onDuty.purpose} onChange={(e) => setOnDuty({ ...onDuty, purpose: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
          <input type="time" value={onDuty.planned_start} onChange={(e) => setOnDuty({ ...onDuty, planned_start: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
          <input type="time" value={onDuty.planned_end} onChange={(e) => setOnDuty({ ...onDuty, planned_end: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
          <button disabled={onDutyRequesting} onClick={submitOnDuty} className="rounded-xl bg-ink text-white px-4 py-2.5 text-sm disabled:opacity-60">{onDutyRequesting ? "Sending…" : "Ask for approval"}</button>
        </div>
        <p className="text-xs text-slate-muted mt-2">Approved On Duty does not consume paid/sick leave. Start and end your actual On Duty session from the Home page.</p>
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">Request remote work</h2>
        <div className="grid md:grid-cols-6 gap-3">
          <select value={remoteWork.work_mode} onChange={(e) => setRemoteWork({ ...remoteWork, work_mode: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm"><option value="wfh">Work From Home</option><option value="other_site">Work From Other Site</option></select>
          <input type="date" value={remoteWork.work_date} onChange={(e) => setRemoteWork({ ...remoteWork, work_date: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
          {remoteWork.work_mode === "other_site" ? <input placeholder="Site name / location" value={remoteWork.site_name} onChange={(e) => setRemoteWork({ ...remoteWork, site_name: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" /> : <div />}
          <input placeholder="Reason / purpose" value={remoteWork.purpose} onChange={(e) => setRemoteWork({ ...remoteWork, purpose: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
          <div className="flex gap-2"><input type="time" value={remoteWork.planned_start} onChange={(e) => setRemoteWork({ ...remoteWork, planned_start: e.target.value })} className="w-full rounded-xl border px-3 py-2.5 text-sm" /><input type="time" value={remoteWork.planned_end} onChange={(e) => setRemoteWork({ ...remoteWork, planned_end: e.target.value })} className="w-full rounded-xl border px-3 py-2.5 text-sm" /></div>
          <button disabled={remoteRequesting} onClick={submitRemoteWork} className="rounded-xl bg-ink text-white px-4 py-2.5 text-sm disabled:opacity-60">{remoteRequesting ? "Sending…" : "Ask for approval"}</button>
        </div>
        <p className="text-xs text-slate-muted mt-2">Employees and Admins can request remote work. Approval is required before the requested date/time. An approved request can be changed before its start; if you edit your own approved request, it returns to Pending approval.</p>
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">My remote work requests</h2>
        {remoteRequests.length === 0 ? <p className="text-sm text-slate-muted">No remote work requests yet.</p> : (
          <div className="space-y-2">
            {remoteRequests.map((x) => <div key={x.id} className="flex flex-wrap items-center justify-between gap-2 border-b last:border-0 py-2 text-sm"><span>{formatDate(x.work_date, { withYear: true })} · {x.work_mode === "wfh" ? "Work From Home" : `Other Site · ${x.site_name || ""}`}</span><span className="capitalize flex items-center gap-2">{x.status.replaceAll("_", " ")}{["pending","approved"].includes(x.status) && <button onClick={() => editRemoteWork(x)} className="rounded-lg border px-2 py-1 text-xs">Change</button>}{["pending","approved"].includes(x.status) && <button onClick={() => cancelRemoteWork(x.id)} className="text-danger text-xs">Cancel</button>}</span></div>)}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">My On Duty requests</h2>
        {onDutyRequests.length === 0 ? <p className="text-sm text-slate-muted">No On Duty requests yet.</p> : (
          <div className="space-y-2">
            {onDutyRequests.map((x) => <div key={x.id} className="flex flex-wrap justify-between gap-2 border-b last:border-0 py-2 text-sm"><span>{formatDate(x.on_duty_date, { withYear: true })} · {x.purpose}</span><span className="capitalize">{x.status.replaceAll("_", " ")}</span></div>)}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">My leave balance</h2>
        <div className="grid grid-cols-2 gap-3">
          <Balance label="Paid" value={`${balance.standard.paid.remaining} remaining`} />
          <Balance label="Sick" value={`${balance.standard.sick.remaining} remaining`} />
          <Balance label="Additional paid" value={balance.additional.paid} />
          <Balance label="Additional sick" value={balance.additional.sick} />
        </div>
        <p className="text-xs text-slate-muted mt-3">Unpaid leave used: {balance.unpaid}</p>
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">My leave requests</h2>
        {leaves.length === 0 ? (
          <p className="text-sm text-slate-muted">No leave requests yet.</p>
        ) : (
          <div className="space-y-2">
            {leaves.map((x) => (
              <div key={x.id} className="flex flex-wrap justify-between gap-2 border-b last:border-0 py-2 text-sm">
                <span>{formatDate(x.leave_date, { withYear: true })}</span>
                <span className="capitalize">{x.leave_type} · {STATUS_LABEL[x.status] || x.status}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <p className="text-xs text-slate-muted">Signed in as {employee?.name}.</p>
    </div>
  );
}

function Balance({ label, value }) {
  return <div className="rounded-xl bg-surface p-3"><p className="text-xs text-slate-muted">{label}</p><p className="text-sm font-semibold text-ink mt-1">{value}</p></div>;
}
