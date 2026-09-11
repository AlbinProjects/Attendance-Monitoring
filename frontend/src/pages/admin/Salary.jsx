import { useEffect, useMemo, useState } from "react";
import api from "../../services/api";
import Card from "../../components/Card";
import LoadingScreen from "../../components/LoadingScreen";
import { useToast } from "../../context/ToastContext";

function money(value) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 2 }).format(Number(value || 0));
}
function days(value) { return Number(value || 0).toFixed(2).replace(/\.00$/, ""); }

export default function Salary() {
  const { showToast } = useToast();
  const [staff, setStaff] = useState([]);
  const [employeeId, setEmployeeId] = useState("");
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [salary, setSalary] = useState("");
  const [statement, setStatement] = useState(null);
  const [loadingStaff, setLoadingStaff] = useState(true);
  const [loadingStatement, setLoadingStatement] = useState(false);
  const [calculating, setCalculating] = useState(false);
  const [savingSalary, setSavingSalary] = useState(false);

  useEffect(() => {
    api.get("/admin/employees")
      .then((res) => setStaff((res.data || []).filter((e) => e.role === "employee" || e.role === "admin")))
      .catch(() => showToast("Couldn't load Employees/Admins.", "error"))
      .finally(() => setLoadingStaff(false));
  }, [showToast]);

  const [year, monthNumber] = month ? month.split("-").map(Number) : [null, null];

  useEffect(() => {
    if (!employeeId || !year || !monthNumber) { setStatement(null); return; }
    setLoadingStatement(true);
    Promise.all([
      api.get("/admin/salary", { params: { employee_id: employeeId, year, month: monthNumber } }),
      api.get("/admin/salary/base", { params: { employee_id: employeeId } }),
    ])
      .then(([statementRes, baseRes]) => {
        const saved = statementRes.data;
        setStatement(saved);
        // Historical/monthly calculation keeps its own salary snapshot. For a
        // month not calculated yet, pre-fill the persistent staff default.
        if (saved?.salary != null) setSalary(String(saved.salary));
        else if (baseRes.data?.monthly_salary != null) setSalary(String(baseRes.data.monthly_salary));
        else setSalary("");
      })
      .catch(() => { setStatement(null); setSalary(""); })
      .finally(() => setLoadingStatement(false));
  }, [employeeId, year, monthNumber]);

  const selected = useMemo(() => staff.find((e) => e.id === employeeId), [staff, employeeId]);

  async function saveDefaultSalary() {
    if (!employeeId) { showToast("Select an Employee or Admin.", "error"); return; }
    const numericSalary = Number(salary);
    if (!Number.isFinite(numericSalary) || numericSalary <= 0) { showToast("Enter a valid monthly salary.", "error"); return; }
    setSavingSalary(true);
    try {
      const res = await api.put("/admin/salary/base", { employee_id: employeeId, salary: numericSalary });
      setSalary(String(res.data.monthly_salary));
      showToast("Default salary saved. It will be pre-filled for future months.");
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't save salary.", "error");
    } finally { setSavingSalary(false); }
  }

  async function calculate() {
    if (!employeeId) { showToast("Select an Employee or Admin.", "error"); return; }
    const numericSalary = Number(salary);
    if (!Number.isFinite(numericSalary) || numericSalary <= 0) { showToast("Enter a valid monthly salary.", "error"); return; }
    setCalculating(true);
    try {
      const res = await api.post("/admin/salary/calculate", {
        employee_id: employeeId,
        year,
        month: monthNumber,
        salary: numericSalary,
      });
      setStatement(res.data);
      setSalary(String(res.data.salary));
      showToast("Salary calculated and saved. This salary is now the default for future months.");
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't calculate salary.", "error");
    } finally { setCalculating(false); }
  }

  if (loadingStaff) return <LoadingScreen />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">Salary</h1>
        <p className="text-sm text-slate-muted mt-1">Monthly salary calculation for Employees and Admins. Super Admins are excluded.</p>
      </div>

      <Card>
        <div className="grid md:grid-cols-3 gap-3 items-end">
          <label className="text-xs text-slate-muted flex flex-col gap-1">
            Employee / Admin
            <select value={employeeId} onChange={(e) => setEmployeeId(e.target.value)} className="rounded-xl border border-border bg-white px-3 py-2.5 text-sm text-ink">
              <option value="">Select staff member</option>
              {staff.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.employee_code} · {e.role.replace("_", " ")}</option>)}
            </select>
          </label>
          <label className="text-xs text-slate-muted flex flex-col gap-1">
            Month
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="rounded-xl border border-border bg-white px-3 py-2.5 text-sm text-ink" />
          </label>
          <label className="text-xs text-slate-muted flex flex-col gap-1">
            Monthly salary (₹)
            <input type="number" min="0.01" step="0.01" value={salary} onChange={(e) => setSalary(e.target.value)} placeholder="e.g. 25000" className="rounded-xl border border-border bg-white px-3 py-2.5 text-sm text-ink" />
          </label>
        </div>
        <div className="mt-4 flex items-center justify-between gap-3 flex-wrap">
          <div>
            <p className="text-xs text-slate-muted">Salary is divided by every calendar day in the selected month, including Sundays and holidays.</p>
            <p className="text-xs text-slate-muted mt-1">The saved default salary is reused automatically for future months. You can change it anytime.</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={saveDefaultSalary} disabled={savingSalary || calculating || !employeeId} className="rounded-xl border border-border bg-white text-ink px-4 py-2.5 text-sm font-medium disabled:opacity-50">
              {savingSalary ? "Saving…" : "Save default salary"}
            </button>
            <button onClick={calculate} disabled={calculating || savingSalary || !employeeId} className="rounded-xl bg-ink text-white px-5 py-2.5 text-sm font-medium disabled:opacity-50">
              {calculating ? "Calculating…" : "Calculate & save"}
            </button>
          </div>
        </div>
      </Card>

      {loadingStatement ? <Card><p className="text-sm text-slate-muted">Loading previous calculation…</p></Card> : statement ? <Statement data={statement} selected={selected} /> : employeeId ? (
        <Card><p className="text-sm text-slate-muted">No saved calculation for this month yet. The saved default salary is pre-filled; calculate when you are ready.</p></Card>
      ) : null}
    </div>
  );
}

function Statement({ data, selected }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Monthly salary" value={money(data.salary)} />
        <Metric label="Deduction days" value={`${days(data.deduction_days)} day${Number(data.deduction_days) === 1 ? "" : "s"}`} />
        <Metric label="Deduction" value={money(data.deduction_amount)} tone="danger" />
        <Metric label="Payable salary" value={money(data.payable_salary)} tone="brand" />
      </div>

      <Card>
        <div className="flex items-center justify-between gap-3 flex-wrap mb-4">
          <div>
            <h2 className="font-semibold text-ink">Full calculation details</h2>
            <p className="text-xs text-slate-muted mt-1">{selected?.name || data.employee_name} · {data.role} · {String(data.month).padStart(2, "0")}/{data.year}</p>
          </div>
          <span className="text-xs text-slate-muted">{data.total_days_in_month} calendar days</span>
        </div>
        <div className="grid md:grid-cols-3 gap-x-6 gap-y-3 text-sm">
          <Line label="Working days considered" value={data.working_days} />
          <Line label="Sundays" value={data.sundays} />
          <Line label="Holidays" value={data.holidays} />
          <Line label="Other non-working" value={data.other_non_working_days} />
          <Line label="Paid leave" value={`${days(data.paid_leave_days)} day`} />
          <Line label="Sick leave" value={`${days(data.sick_leave_days)} day`} />
          <Line label="Unpaid leave" value={`${days(data.unpaid_leave_days)} day`} />
          <Line label="Unpaid half leave" value={`${days(data.unpaid_half_leave_days)} day`} />
          <Line label="Work From Other Site" value={`${data.other_site_days} day${data.other_site_days === 1 ? "" : "s"}`} />
          <Line label="On Duty" value={`${data.on_duty_days} day${data.on_duty_days === 1 ? "" : "s"}`} />
          <Line label="Days below 8 hours" value={data.short_8h_days} />
          <Line label="Short-day penalty" value={`${days(data.short_day_penalty_days)} day`} />
          <Line label="Per-day salary" value={money(data.per_day_salary)} />
          <Line label="Total deduction days" value={days(data.deduction_days)} />
          <Line label="Elapsed days considered" value={data.elapsed_days_considered} />
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold text-ink mb-3">Reduction breakdown</h2>
        {data.details?.length ? (
          <div className="space-y-2">
            {data.details.map((item, index) => (
              <div key={`${item.type}-${item.date || "summary"}-${index}`} className="rounded-xl border border-border px-3 py-3 text-sm flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                <div>
                  <p className="font-medium text-ink">{item.type === "unpaid_leave" ? "Unpaid leave" : item.type === "unpaid_half_leave" ? "Unpaid half leave" : item.type === "short_8h_day" ? "Below 8-hour day" : "8-hour short-day threshold penalty"}{item.date ? ` · ${item.date}` : ""}</p>
                  <p className="text-xs text-slate-muted mt-0.5">{item.reason || ""}{item.half_day_period ? ` · ${item.half_day_period}` : ""}{item.worked_hours != null ? ` · Worked ${item.worked_hours}h` : ""}</p>
                </div>
                <span className="font-mono font-semibold text-danger">{days(item.deduction_days)} deduction day{Number(item.deduction_days) === 1 ? "" : "s"}</span>
              </div>
            ))}
          </div>
        ) : <p className="text-sm text-slate-muted">No salary reductions were applicable.</p>}
      </Card>

      <Card className="bg-surface">
        <p className="text-xs text-slate-muted"><strong>Rule:</strong> Unpaid leave = 1 day, approved half-day leave = 0.5 day. If more than 3 eligible working days in the month are below 8 hours, one additional unpaid half-day (0.5 day) is applied. Work From Other Site and On Duty are exempt from the 8-hour rule.</p>
      </Card>
    </div>
  );
}

function Metric({ label, value, tone }) { return <Card className="!p-4"><p className="text-xs text-slate-muted">{label}</p><p className={`text-lg font-semibold mt-1 ${tone === "danger" ? "text-danger" : tone === "brand" ? "text-brand-dark" : "text-ink"}`}>{value}</p></Card>; }
function Line({ label, value }) { return <div className="flex justify-between gap-3 border-b border-border pb-2"><span className="text-slate-muted">{label}</span><span className="font-medium text-ink">{value}</span></div>; }
