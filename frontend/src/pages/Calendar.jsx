import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../services/api";
import Card from "../components/Card";
import LoadingScreen from "../components/LoadingScreen";
import { formatDate } from "../utils/formatters";

export default function Calendar() {
  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [days, setDays] = useState(null);
  const [leaves, setLeaves] = useState([]);
  const [balance, setBalance] = useState(null);
  const load = useCallback(async () => {
    const [calendarRes, leaveRes, balanceRes] = await Promise.all([
      api.get(`/calendar/month?year=${year}&month=${month}`),
      api.get("/calendar/leave"),
      api.get("/calendar/leave/balance"),
    ]);
    setDays(calendarRes.data); setLeaves(leaveRes.data); setBalance(balanceRes.data);
  }, [year, month]);
  useEffect(() => { load(); }, [load]);
  const leaveByDate = useMemo(() => Object.fromEntries(leaves.filter(x => x.status === "approved").map(x => [x.leave_date, x])), [leaves]);
  if (!days || !balance) return <LoadingScreen />;
  return <div className="space-y-5">
    <div className="flex items-center justify-between"><h1 className="text-xl font-semibold text-ink">Company Calendar</h1><div className="flex gap-2"><button className="rounded-lg border px-3 py-1.5" onClick={() => { if (month===1){setYear(year-1);setMonth(12)}else setMonth(month-1)}}>‹</button><span className="py-1.5 text-sm font-medium min-w-28 text-center">{new Date(year, month-1, 1).toLocaleString(undefined,{month:"long",year:"numeric"})}</span><button className="rounded-lg border px-3 py-1.5" onClick={() => { if(month===12){setYear(year+1);setMonth(1)}else setMonth(month+1)}}>›</button></div></div>
    <Card><div className="grid grid-cols-7 gap-1 text-center text-xs text-slate-muted mb-2">{["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].map(x=><div key={x}>{x}</div>)}</div><div className="grid grid-cols-7 gap-1">{days.map(d => { const leave=leaveByDate[d.calendar_date]; return <div key={d.calendar_date} className={`min-h-16 rounded-lg border p-1.5 ${d.is_working_day?"bg-white":"bg-slate-50"}`}><div className="text-xs font-medium">{Number(d.calendar_date.slice(-2))}</div><div className="text-[10px] mt-1 truncate">{leave ? `${leave.leave_type} leave` : d.is_working_day ? "Working" : (d.name || d.day_type.replaceAll("_"," "))}</div></div>})}</div></Card>
    <Card><h2 className="font-semibold text-ink mb-3">My leave balance</h2><div className="grid grid-cols-2 gap-3"><Balance label="Paid" value={`${balance.standard.paid.remaining} remaining`} /><Balance label="Sick" value={`${balance.standard.sick.remaining} remaining`} /><Balance label="Additional paid" value={balance.additional.paid} /><Balance label="Additional sick" value={balance.additional.sick} /></div><p className="text-xs text-slate-muted mt-3">Unpaid leave used: {balance.unpaid}</p></Card>
    <Card><h2 className="font-semibold text-ink mb-3">My approved leave</h2>{leaves.filter(x=>x.status==="approved").length===0?<p className="text-sm text-slate-muted">No approved leave.</p>:<div className="space-y-2">{leaves.filter(x=>x.status==="approved").map(x=><div key={x.id} className="flex justify-between text-sm"><span>{formatDate(x.leave_date,{withYear:true})}</span><span className="capitalize text-slate-muted">{x.leave_type}{x.is_additional?" · additional":""}</span></div>)}</div>}</Card>
  </div>;
}
function Balance({label,value}){return <div className="rounded-xl bg-surface p-3"><p className="text-xs text-slate-muted">{label}</p><p className="text-sm font-semibold text-ink mt-1">{value}</p></div>}
