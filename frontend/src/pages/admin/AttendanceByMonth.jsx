import { useCallback, useEffect, useState } from "react";
import api from "../../services/api";
import Card from "../../components/Card";
import LoadingScreen from "../../components/LoadingScreen";

function pad(n) { return String(n).padStart(2, "0"); }
function monthValue(year, month) { return `${year}-${pad(month)}`; }
function shift(year, month, delta) { const d = new Date(year, month - 1 + delta, 1); return [d.getFullYear(), d.getMonth()+1]; }
function cellClass(status) {
  if (status?.includes("leave")) return "bg-amber-50 text-amber border-amber-100";
  if (status === "present") return "bg-brand-tint text-brand-dark border-transparent";
  if (status === "late") return "bg-amber-tint text-amber border-transparent";
  if (status === "wfh") return "bg-blue-50 text-blue-700 border-blue-100";
  if (status === "other_site" || status === "on_duty") return "bg-blue-50 text-blue-700 border-blue-100";
  if (status === "missed_check_in" || status === "checkout_missed" || status === "not_completed_8h") return "bg-danger-tint text-danger border-transparent";
  if (status === "holiday") return "bg-red-50 text-red-700 border-red-100";
  if (status === "sunday" || status === "other_non_working" || status === "upcoming" || status === "before_history") return "bg-surface text-slate-muted border-border";
  return "bg-white text-slate-muted border-border";
}
function shortLabel(cell) {
  const map = {
    present: "Present", late: "Late", missed_check_in: "Missed check-in", checkout_missed: "Check-out missed",
    not_completed_8h: "<8h", sunday: "Sunday", holiday: "Holiday", other_non_working: "Non-working",
    other_site: "Other Site", on_duty: "On Duty", wfh: "WFH", upcoming: "—", before_history: "—",
    paid_leave: "Paid leave", sick_leave: "Sick leave", unpaid_leave: "Unpaid leave", half_day_leave: "Half-day",
  };
  return map[cell?.status] || cell?.label || "—";
}

export default function AttendanceByMonth() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth()+1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setLoading(true); setError("");
    return api.get("/admin/attendance/monthly", { params: { year, month } })
      .then((res) => setData(res.data))
      .catch((err) => { setData(null); setError(err?.response?.data?.detail || "Couldn't load monthly attendance."); })
      .finally(() => setLoading(false));
  }, [year, month]);
  useEffect(() => { load(); }, [load]);

  function move(delta) { const [y,m] = shift(year,month,delta); setYear(y); setMonth(m); }
  if (loading && !data) return <LoadingScreen />;

  return <div className="space-y-5">
    <div className="flex items-center justify-between gap-3 flex-wrap">
      <div><h1 className="text-xl font-semibold text-ink">Attendance by Month</h1><p className="text-sm text-slate-muted mt-1">Employees and Admins only. Super Admins are excluded.</p></div>
      <div className="flex items-center gap-2"><button onClick={() => move(-1)} className="rounded-xl border border-border bg-white px-3 py-2 text-sm font-medium">← Previous</button><input type="month" value={monthValue(year,month)} onChange={(e)=>{const [y,m]=e.target.value.split("-").map(Number);setYear(y);setMonth(m);}} className="rounded-xl border border-border bg-white px-3 py-2 text-sm"/><button onClick={() => move(1)} className="rounded-xl border border-border bg-white px-3 py-2 text-sm font-medium">Next →</button></div>
    </div>
    {error && <Card><p className="text-sm text-danger">{error}</p></Card>}
    <Card className="!p-0 overflow-hidden">
      <div className="overflow-x-auto">
        <table className="text-xs border-collapse min-w-max">
          <thead><tr className="border-b border-border bg-surface"><th className="sticky left-0 z-10 bg-surface px-3 py-3 text-left min-w-[210px]">Staff</th>{(data?.days || []).map((d)=><th key={d.date} className="px-1 py-2 min-w-[58px] text-center"><div className="font-semibold">{d.day}</div><div className="text-[10px] text-slate-muted">{new Date(`${d.date}T00:00:00`).toLocaleDateString(undefined,{weekday:"short"}).slice(0,3)}</div></th>)}</tr></thead>
          <tbody>{(data?.staff || []).map((person)=><tr key={person.employee_id} className="border-b border-border last:border-0 hover:bg-surface/50"><td className="sticky left-0 z-10 bg-white px-3 py-2.5 min-w-[210px]"><p className="font-medium text-ink">{person.name}</p><p className="text-[10px] text-slate-muted">{person.employee_code} · {person.role === "admin" ? "Admin" : "Employee"}{person.department ? ` · ${person.department}` : ""}</p></td>{(person.cells || []).map((cell)=><td key={cell.date} className="px-1 py-1 text-center align-middle"><div title={cell.label} className={`min-h-[38px] rounded-lg border px-1 py-1 flex items-center justify-center font-medium leading-tight ${cellClass(cell.status)}`}>{shortLabel(cell)}</div></td>)}</tr>)}</tbody>
        </table>
      </div>
    </Card>
    <Card><div className="flex flex-wrap gap-2 text-xs">
      <Legend cls="bg-brand-tint text-brand-dark" label="Present"/><Legend cls="bg-amber-tint text-amber" label="Late"/><Legend cls="bg-amber-50 text-amber" label="Leave"/><Legend cls="bg-blue-50 text-blue-700" label="WFH / Other Site / On Duty"/><Legend cls="bg-danger-tint text-danger" label="Missed / <8h"/><Legend cls="bg-red-50 text-red-700" label="Holiday"/><Legend cls="bg-surface text-slate-muted" label="Sunday / Non-working"/>
    </div></Card>
  </div>;
}
function Legend({cls,label}) { return <span className={`rounded-full px-2.5 py-1 ${cls}`}>{label}</span>; }
