import { useCallback, useEffect, useState } from "react";
import api from "../../services/api";
import Card from "../../components/Card";
import LoadingScreen from "../../components/LoadingScreen";
import { useToast } from "../../context/ToastContext";
import { useAuth } from "../../context/AuthContext";

const STATUS_LABEL = { pending: "Pending", approved: "Approved", rejected: "Rejected", cancelled: "Cancelled" };

export default function AdminCalendar() {
  const { employee: currentEmployee } = useAuth();
  const { showToast } = useToast();
  const isSuperAdmin = currentEmployee?.role === "super_admin";
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [days, setDays] = useState(null);
  const [employees, setEmployees] = useState([]);
  const [leaves, setLeaves] = useState([]);
  const [pending, setPending] = useState([]);
  const [pendingOnDuty, setPendingOnDuty] = useState([]);
  const [pendingRemote, setPendingRemote] = useState([]);
  const [remoteHistory, setRemoteHistory] = useState([]);
  const [directRemote, setDirectRemote] = useState({ employee_id: "", work_mode: "wfh", work_date: "", purpose: "", site_name: "", planned_start: "", planned_end: "" });
  const [directOnDuty, setDirectOnDuty] = useState({ employee_id: "", on_duty_date: "", purpose: "", planned_start: "", planned_end: "" });
  const [form, setForm] = useState({ calendar_date: "", day_type: "working_day", is_working_day: true, name: "" });
  const [leave, setLeave] = useState({ employee_id: "", leave_date: "", leave_type: "paid", is_additional: false, reason: "" });
  const [myRequest, setMyRequest] = useState({ leave_date: "", leave_type: "paid", reason: "" });

  const load = useCallback(async () => {
    const requests = [
      api.get(`/calendar/month?year=${year}&month=${month}`),
      api.get("/admin/employees?is_active=true"),
      api.get("/calendar/admin/leave"),
      api.get("/calendar/admin/leave?status=pending"),
      api.get("/calendar/admin/on-duty"),
      api.get("/calendar/admin/remote-work"),
      api.get("/calendar/admin/remote-work/all"),
    ];
    const [c, e, l, p, od, rw, rh] = await Promise.all(requests);
    setDays(c.data); setEmployees(e.data); setLeaves(l.data); setPending(p.data); setPendingOnDuty(od.data); setPendingRemote(rw.data); setRemoteHistory(rh.data);
  }, [year, month]);

  useEffect(() => { load().catch(() => {}); }, [load]);

  if (!days) return <LoadingScreen />;

  async function saveCalendar() {
    if (!form.calendar_date) return;
    try {
      await api.put(`/calendar/admin/date/${form.calendar_date}`, null, { params: { day_type: form.day_type, is_working_day: form.is_working_day, name: form.name || undefined } });
      showToast("Calendar updated."); await load();
    } catch (e) { showToast(e?.response?.data?.detail || "Couldn't update calendar.", "error"); }
  }

  async function grant() {
    try {
      await api.post("/calendar/admin/leave", null, { params: leave });
      showToast("Leave granted."); setLeave({ ...leave, reason: "" }); await load();
    } catch (e) { showToast(e?.response?.data?.detail || "Couldn't grant leave.", "error"); }
  }

  async function requestMyLeave() {
    if (!myRequest.leave_date || !myRequest.reason.trim()) { showToast("Select a date and enter a reason.", "error"); return; }
    try {
      await api.post("/calendar/leave/request", null, { params: myRequest });
      showToast("Your leave request was sent for approval."); setMyRequest({ ...myRequest, reason: "" }); await load();
    } catch (e) { showToast(e?.response?.data?.detail || "Couldn't submit leave request.", "error"); }
  }

  async function approve(id) {
    try { await api.post(`/calendar/admin/leave/${id}/approve`); showToast("Leave request approved."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't approve leave request.", "error"); }
  }

  async function reject(id) {
    const reason = window.prompt("Reason for rejection (optional):") || "";
    try { await api.post(`/calendar/admin/leave/${id}/reject`, null, { params: { reason } }); showToast("Leave request rejected."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't reject leave request.", "error"); }
  }

  async function approveOnDuty(id) {
    try { await api.post(`/calendar/admin/on-duty/${id}/approve`); showToast("On Duty request approved."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't approve On Duty request.", "error"); }
  }

  async function rejectOnDuty(id) {
    const reason = window.prompt("Reason for rejection (optional):") || "";
    try { await api.post(`/calendar/admin/on-duty/${id}/reject`, null, { params: { reason } }); showToast("On Duty request rejected."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't reject On Duty request.", "error"); }
  }

  async function approveRemote(id) {
    try { await api.post(`/calendar/admin/remote-work/${id}/approve`); showToast("Remote work request approved."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't approve remote work request.", "error"); }
  }

  async function rejectRemote(id) {
    const reason = window.prompt("Reason for rejection (optional):") || "";
    try { await api.post(`/calendar/admin/remote-work/${id}/reject`, null, { params: { reason } }); showToast("Remote work request rejected."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't reject remote work request.", "error"); }
  }

  async function editRemote(id) {
    const item = remoteHistory.find(x => x.id === id); if (!item) return;
    const work_mode = window.prompt("Type: wfh or other_site", item.work_mode); if (!work_mode || !["wfh","other_site"].includes(work_mode)) return;
    const work_date = window.prompt("Date (YYYY-MM-DD)", item.work_date); if (!work_date) return;
    const purpose = window.prompt("Purpose", item.purpose || ""); if (!purpose) return;
    const site_name = work_mode === "other_site" ? (window.prompt("Site name / location", item.site_name || "") || "") : "";
    const planned_start = window.prompt("Start time (HH:MM, optional)", item.planned_start || "") || "";
    const planned_end = window.prompt("End time (HH:MM, optional)", item.planned_end || "") || "";
    try { await api.put(`/calendar/remote-work/${id}`, null, { params: { work_mode, work_date, purpose, site_name, planned_start, planned_end } }); showToast("Remote work updated."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't update remote work.", "error"); }
  }

  async function cancelRemote(id) {
    if (!window.confirm("Cancel this remote work approval/assignment?")) return;
    try { await api.delete(`/calendar/remote-work/${id}`); showToast("Remote work cancelled."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't cancel remote work.", "error"); }
  }

  async function assignRemote() {
    if (!directRemote.employee_id || !directRemote.work_date || !directRemote.purpose.trim()) { showToast("Select an employee, date and purpose.", "error"); return; }
    if (directRemote.work_mode === "other_site" && !directRemote.site_name.trim()) { showToast("Enter the other work site's name/location.", "error"); return; }
    try { await api.post("/calendar/admin/remote-work", null, { params: directRemote }); showToast("Remote work assigned directly."); setDirectRemote({ ...directRemote, purpose: "", site_name: "", planned_start: "", planned_end: "" }); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't assign remote work.", "error"); }
  }

  async function grantDirectOnDuty() {
    if (!directOnDuty.employee_id || !directOnDuty.on_duty_date || !directOnDuty.purpose.trim()) { showToast("Select an employee, date and purpose.", "error"); return; }
    try {
      await api.post("/calendar/admin/on-duty", null, { params: directOnDuty });
      showToast("On Duty marked directly.");
      setDirectOnDuty({ ...directOnDuty, purpose: "", planned_start: "", planned_end: "" });
      await load();
    } catch (e) { showToast(e?.response?.data?.detail || "Couldn't mark On Duty.", "error"); }
  }

  async function cancel(id) {
    try { await api.delete(`/calendar/admin/leave/${id}`, { params: { reason: "Cancelled by administrator" } }); showToast("Leave cancelled."); await load(); }
    catch (e) { showToast(e?.response?.data?.detail || "Couldn't cancel leave.", "error"); }
  }

  const leadingEmpty = new Date(year, month - 1, 1).getDay();
  const employeeName = (id) => employees.find((e) => e.id === id)?.name || id;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold text-ink">Calendar & Leave</h1>
        <div className="flex gap-2">
          <button className="rounded-lg border px-3 py-1.5" onClick={() => month === 1 ? (setYear(year - 1), setMonth(12)) : setMonth(month - 1)}>‹</button>
          <span className="py-1.5 text-sm font-medium min-w-28 text-center">{new Date(year, month - 1, 1).toLocaleString(undefined, { month: "long", year: "numeric" })}</span>
          <button className="rounded-lg border px-3 py-1.5" onClick={() => month === 12 ? (setYear(year + 1), setMonth(1)) : setMonth(month + 1)}>›</button>
        </div>
      </div>

      {currentEmployee?.role === "admin" && (
        <Card>
          <h2 className="font-semibold mb-3">Request leave for myself</h2>
          <div className="grid md:grid-cols-4 gap-3">
            <input type="date" value={myRequest.leave_date} onChange={(e) => setMyRequest({ ...myRequest, leave_date: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
            <select value={myRequest.leave_type} onChange={(e) => setMyRequest({ ...myRequest, leave_type: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm"><option value="paid">Paid leave</option><option value="sick">Sick leave</option></select>
            <input placeholder="Reason" value={myRequest.reason} onChange={(e) => setMyRequest({ ...myRequest, reason: e.target.value })} className="rounded-xl border px-3 py-2.5 text-sm" />
            <button onClick={requestMyLeave} className="rounded-xl bg-ink text-white px-4 text-sm">Ask Super Admin</button>
          </div>
          <p className="text-xs text-slate-muted mt-2">Admin leave requests require Super Admin approval.</p>
        </Card>
      )}

      {pending.length > 0 && (
        <Card>
          <h2 className="font-semibold mb-3">Pending leave requests</h2>
          <div className="space-y-2">
            {pending.map((x) => {
              const target = employees.find((e) => e.id === x.employee_id);
              const canAct = isSuperAdmin || target?.role !== "admin";
              return <div key={x.id} className="flex flex-wrap items-center justify-between gap-3 border-b last:border-0 py-2 text-sm">
                <div><p className="font-medium">{employeeName(x.employee_id)} <span className="text-slate-muted capitalize">({target?.role?.replace("_", " ") || "employee"})</span></p><p className="text-xs text-slate-muted">{x.leave_date} · {x.leave_type} · {x.reason}</p></div>
                {canAct ? <div className="flex gap-2"><button onClick={() => approve(x.id)} className="rounded-lg bg-ink text-white px-3 py-1.5 text-xs">Approve</button><button onClick={() => reject(x.id)} className="rounded-lg border px-3 py-1.5 text-xs">Reject</button></div> : <span className="text-xs text-slate-muted">Super Admin approval required</span>}
              </div>;
            })}
          </div>
        </Card>
      )}

      {pendingOnDuty.length > 0 && (
        <Card>
          <h2 className="font-semibold mb-3">Pending On Duty requests</h2>
          <div className="space-y-2">
            {pendingOnDuty.map((x) => {
              const target = employees.find((e) => e.id === x.employee_id);
              const canAct = isSuperAdmin || target?.role !== "admin";
              return <div key={x.id} className="flex flex-wrap items-center justify-between gap-3 border-b last:border-0 py-2 text-sm">
                <div><p className="font-medium">{employeeName(x.employee_id)} <span className="text-slate-muted capitalize">({target?.role?.replace("_", " ") || "employee"})</span></p><p className="text-xs text-slate-muted">{x.on_duty_date} · {x.purpose}{x.planned_start ? ` · ${x.planned_start}${x.planned_end ? `–${x.planned_end}` : ""}` : ""}</p></div>
                {canAct ? <div className="flex gap-2"><button onClick={() => approveOnDuty(x.id)} className="rounded-lg bg-ink text-white px-3 py-1.5 text-xs">Approve</button><button onClick={() => rejectOnDuty(x.id)} className="rounded-lg border px-3 py-1.5 text-xs">Reject</button></div> : <span className="text-xs text-slate-muted">Super Admin approval required</span>}
              </div>;
            })}
          </div>
        </Card>
      )}

      {pendingRemote.length > 0 && (
        <Card>
          <h2 className="font-semibold mb-3">Pending remote work requests</h2>
          <div className="space-y-2">
            {pendingRemote.map((x) => {
              const target = employees.find((e) => e.id === x.employee_id);
              const canAct = isSuperAdmin || target?.role !== "admin";
              return <div key={x.id} className="flex flex-wrap items-center justify-between gap-3 border-b last:border-0 py-2 text-sm">
                <div><p className="font-medium">{employeeName(x.employee_id)} <span className="text-slate-muted capitalize">({target?.role?.replace("_", " ") || "employee"})</span></p><p className="text-xs text-slate-muted">{x.work_date} · {x.work_mode === "wfh" ? "Work From Home" : `Other Site · ${x.site_name || ""}`} · {x.purpose}{x.planned_start ? ` · ${x.planned_start}${x.planned_end ? `–${x.planned_end}` : ""}` : ""}</p></div>
                {canAct ? <div className="flex gap-2"><button onClick={() => approveRemote(x.id)} className="rounded-lg bg-ink text-white px-3 py-1.5 text-xs">Approve</button><button onClick={() => rejectRemote(x.id)} className="rounded-lg border px-3 py-1.5 text-xs">Reject</button></div> : <span className="text-xs text-slate-muted">Super Admin approval required</span>}
              </div>;
            })}
          </div>
        </Card>
      )}

      <Card>
        <h2 className="font-semibold mb-3">Approved / assigned remote work</h2>
        <div className="space-y-2">
          {remoteHistory.filter(x => ["approved","assigned"].includes(x.status)).length === 0 ? <p className="text-sm text-slate-muted">No upcoming approved remote work.</p> : remoteHistory.filter(x => ["approved","assigned"].includes(x.status)).map(x => <div key={x.id} className="flex flex-wrap items-center justify-between gap-2 border-b last:border-0 py-2 text-sm"><span>{employeeName(x.employee_id)} · {x.work_date} · {x.work_mode === "wfh" ? "Work From Home" : `Other Site · ${x.site_name || ""}`}</span><span className="flex gap-2"><button onClick={() => editRemote(x.id)} className="rounded-lg border px-2 py-1 text-xs">Change</button><button onClick={() => cancelRemote(x.id)} className="text-danger text-xs">Cancel</button></span></div>)}
        </div>
        <p className="text-xs text-slate-muted mt-2">Approved or directly assigned remote work can be changed before its requested date/time. After the start point, it becomes locked.</p>
      </Card>

      <Card>
        <h2 className="font-semibold mb-3">Assign remote work directly</h2>
        <div className="grid md:grid-cols-7 gap-3">
          <select value={directRemote.employee_id} onChange={e => setDirectRemote({...directRemote, employee_id:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"><option value="">Employee / Admin</option>{employees.filter(e => e.role !== "super_admin").map(e => <option key={e.id} value={e.id}>{e.name} ({e.role.replace("_", " ")})</option>)}</select>
          <select value={directRemote.work_mode} onChange={e => setDirectRemote({...directRemote, work_mode:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"><option value="wfh">Work From Home</option><option value="other_site">Other Site</option></select>
          <input type="date" value={directRemote.work_date} onChange={e => setDirectRemote({...directRemote, work_date:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm" />
          {directRemote.work_mode === "other_site" ? <input placeholder="Site name / location" value={directRemote.site_name} onChange={e => setDirectRemote({...directRemote, site_name:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm" /> : <div />}
          <input placeholder="Purpose" value={directRemote.purpose} onChange={e => setDirectRemote({...directRemote, purpose:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm" />
          <div className="flex gap-2"><input type="time" value={directRemote.planned_start} onChange={e => setDirectRemote({...directRemote, planned_start:e.target.value})} className="w-full rounded-xl border px-3 py-2.5 text-sm" /><input type="time" value={directRemote.planned_end} onChange={e => setDirectRemote({...directRemote, planned_end:e.target.value})} className="w-full rounded-xl border px-3 py-2.5 text-sm" /></div>
          <button onClick={assignRemote} className="rounded-xl bg-ink text-white px-4 text-sm">Assign</button>
        </div>
        <p className="text-xs text-slate-muted mt-2">Admins and Super Admins can assign remote work directly. Direct assignments are immediately approved and need no further approval. They can still be changed or cancelled before the requested date/time.</p>
      </Card>

      {isSuperAdmin && (
        <Card>
          <h2 className="font-semibold mb-3">Directly mark On Duty</h2>
          <div className="grid md:grid-cols-5 gap-3">
            <select value={directOnDuty.employee_id} onChange={e => setDirectOnDuty({...directOnDuty, employee_id:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"><option value="">Employee / Admin</option>{employees.filter(e => e.role !== "super_admin").map(e => <option key={e.id} value={e.id}>{e.name} ({e.role.replace("_", " ")})</option>)}</select>
            <input type="date" value={directOnDuty.on_duty_date} onChange={e => setDirectOnDuty({...directOnDuty, on_duty_date:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm" />
            <input placeholder="Purpose" value={directOnDuty.purpose} onChange={e => setDirectOnDuty({...directOnDuty, purpose:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm" />
            <div className="flex gap-2"><input type="time" value={directOnDuty.planned_start} onChange={e => setDirectOnDuty({...directOnDuty, planned_start:e.target.value})} className="w-full rounded-xl border px-3 py-2.5 text-sm" /><input type="time" value={directOnDuty.planned_end} onChange={e => setDirectOnDuty({...directOnDuty, planned_end:e.target.value})} className="w-full rounded-xl border px-3 py-2.5 text-sm" /></div>
            <button onClick={grantDirectOnDuty} className="rounded-xl bg-ink text-white px-4 text-sm">Mark On Duty</button>
          </div>
          <p className="text-xs text-slate-muted mt-2">Only Super Admin can directly mark On Duty. This does not consume leave.</p>
        </Card>
      )}

      <Card><h2 className="font-semibold mb-3">Set company date</h2><div className="grid md:grid-cols-4 gap-3"><input type="date" value={form.calendar_date} onChange={e => setForm({...form,calendar_date:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"/><select value={form.day_type} onChange={e=>setForm({...form,day_type:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"><option value="working_day">Working day</option><option value="sunday">Sunday</option><option value="holiday">Holiday</option><option value="other_non_working">Other non-working</option></select><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.is_working_day} onChange={e=>setForm({...form,is_working_day:e.target.checked})}/> Working</label><div className="flex gap-2"><input placeholder="Name" value={form.name} onChange={e=>setForm({...form,name:e.target.value})} className="min-w-0 flex-1 rounded-xl border px-3 py-2.5 text-sm"/><button onClick={saveCalendar} className="rounded-xl bg-ink text-white px-4 text-sm">Save</button></div></div></Card>

      <Card><div className="grid grid-cols-7 gap-1 text-center text-xs text-slate-muted mb-2">{["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].map(x=><div key={x}>{x}</div>)}</div><div className="grid grid-cols-7 gap-1">{Array.from({length:leadingEmpty}).map((_,i)=><div key={`empty-${i}`} />)}{days.map(d=><button key={d.calendar_date} onClick={()=>setForm({calendar_date:d.calendar_date,day_type:d.day_type,is_working_day:d.is_working_day,name:d.name||""})} className={`min-h-16 rounded-lg border p-1.5 text-left ${d.is_working_day?"bg-white":"bg-slate-50"}`}><div className="text-xs font-medium">{Number(d.calendar_date.slice(-2))}</div><div className="text-[10px] mt-1 truncate">{d.name||d.day_type.replaceAll("_"," ")}</div></button>)}</div></Card>

      <Card><h2 className="font-semibold mb-3">Grant leave</h2><div className="grid md:grid-cols-6 gap-3"><select value={leave.employee_id} onChange={e=>setLeave({...leave,employee_id:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"><option value="">Employee</option>{employees.map(e=><option key={e.id} value={e.id}>{e.name} ({e.employee_code})</option>)}</select><input type="date" value={leave.leave_date} onChange={e=>setLeave({...leave,leave_date:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"/><select value={leave.leave_type} onChange={e=>setLeave({...leave,leave_type:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"><option value="paid">Paid</option><option value="sick">Sick</option><option value="unpaid">Unpaid</option></select>{isSuperAdmin&&<label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={leave.is_additional} onChange={e=>setLeave({...leave,is_additional:e.target.checked})}/> Additional</label>}<input placeholder="Reason" value={leave.reason} onChange={e=>setLeave({...leave,reason:e.target.value})} className="rounded-xl border px-3 py-2.5 text-sm"/><button onClick={grant} className="rounded-xl bg-ink text-white px-4 text-sm">Grant leave</button></div><p className="text-xs text-slate-muted mt-2">Additional paid/sick leave is restricted to Super Admin. Admins can grant unpaid only after standard paid and sick allocations are used.</p></Card>

      <Card><h2 className="font-semibold mb-3">Leave records</h2><div className="space-y-2">{leaves.filter(x=>x.status!=="pending").map(x=><div key={x.id} className="flex flex-wrap items-center justify-between gap-2 border-b last:border-0 py-2 text-sm"><span>{employeeName(x.employee_id)} · {x.leave_date}</span><span className="capitalize">{x.leave_type} · {STATUS_LABEL[x.status] || x.status}{x.is_additional?" · additional":""}</span>{x.status==="approved"&&<button onClick={()=>cancel(x.id)} className="text-danger text-xs">Cancel</button>}</div>)}{leaves.filter(x=>x.status!=="pending").length===0&&<p className="text-sm text-slate-muted">No leave records.</p>}</div></Card>
    </div>
  );
}
