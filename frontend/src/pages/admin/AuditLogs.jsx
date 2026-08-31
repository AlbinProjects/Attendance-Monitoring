import { useEffect, useMemo, useState } from "react";
import api from "../../services/api";
import Card from "../../components/Card";
import FilterSelect from "../../components/admin/FilterSelect";
import { formatTime } from "../../utils/formatters";

const ACTION_OPTIONS = [
  { value: "CHECK_IN", label: "Check-in" },
  { value: "CHECK_OUT", label: "Check-out" },
  { value: "ADMIN_ATTENDANCE_CREATED", label: "Manual attendance created" },
  { value: "ADMIN_ATTENDANCE_UPDATED", label: "Attendance corrected" },
  { value: "EMPLOYEE_CREATED", label: "Employee created" },
  { value: "EMPLOYEE_UPDATED", label: "Employee updated" },
  { value: "EMPLOYEE_ROLE_CHANGED", label: "Role changed" },
  { value: "EMPLOYEE_DISABLED", label: "Employee disabled" },
];

export default function AuditLogs() {
  const [employees, setEmployees] = useState([]);
  const [logs, setLogs] = useState(null);
  const [filters, setFilters] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/admin/employees").then((res) => setEmployees(res.data));
  }, []);

  const employeeOptions = useMemo(
    () => employees.map((e) => ({ value: e.id, label: e.name })),
    [employees]
  );
  const employeeById = useMemo(() => Object.fromEntries(employees.map((e) => [e.id, e.name])), [employees]);

  useEffect(() => {
    setLoading(true);
    api
      .get("/admin/audit", { params: filters })
      .then((res) => setLogs(res.data))
      .finally(() => setLoading(false));
  }, [filters]);

  function setFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-ink">Audit log</h1>
        <p className="text-sm text-slate-muted mt-1">
          Every manual attendance change and employee change, permanently recorded. Nothing here
          can be edited or deleted.
        </p>
      </div>

      <Card className="!p-4">
        <div className="flex flex-wrap gap-3">
          <label className="text-xs text-slate-muted flex flex-col gap-1">
            Date
            <input
              type="date"
              value={filters.date ?? ""}
              onChange={(e) => setFilter("date", e.target.value || undefined)}
              className="rounded-lg border border-border bg-white px-2.5 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40"
            />
          </label>
          <FilterSelect label="Employee" value={filters.employee_id} onChange={(v) => setFilter("employee_id", v)} options={employeeOptions} />
          <FilterSelect label="Action" value={filters.action} onChange={(v) => setFilter("action", v)} options={ACTION_OPTIONS} />
        </div>
      </Card>

      <div className="space-y-2.5">
        {loading ? (
          <Card className="text-center py-8 text-slate-muted text-sm">Loading…</Card>
        ) : logs?.length === 0 ? (
          <Card className="text-center py-8 text-slate-muted text-sm">No audit entries match these filters.</Card>
        ) : (
          logs?.map((log) => (
            <Card key={log.id} className="!p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-sm font-medium text-ink">{formatAction(log.action)}</p>
                  <p className="text-xs text-slate-muted mt-0.5">
                    {employeeById[log.employee_id] || "Unknown employee"} · by{" "}
                    {employeeById[log.performed_by] || "system"}
                  </p>
                  {log.reason && <p className="text-xs text-ink mt-1.5">“{log.reason}”</p>}
                </div>
                <p className="text-xs font-mono text-slate-muted whitespace-nowrap">
                  {formatTime(log.created_at)}
                </p>
              </div>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}

function formatAction(action) {
  const found = ACTION_OPTIONS.find((a) => a.value === action);
  return found ? found.label : action;
}
