import { useEffect, useMemo, useState } from "react";
import api from "../../services/api";
import Card from "../../components/Card";
import StatusBadge from "../../components/StatusBadge";
import FilterSelect from "../../components/admin/FilterSelect";
import { downloadCsv } from "../../utils/exportCsv";
import { formatDate, formatTime } from "../../utils/formatters";

const STATUS_OPTIONS = [
  { value: "not_available", label: "Not available" },
  { value: "available", label: "Available" },
  { value: "submitted", label: "Submitted" },
  { value: "missing", label: "Missing" },
  { value: "backdated", label: "Backdated" },
];

export default function AdminPerformance() {
  const [employees, setEmployees] = useState([]);
  const [rows, setRows] = useState(null);
  const [filters, setFilters] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get("/admin/employees").then((res) => setEmployees(res.data));
  }, []);

  const departmentOptions = useMemo(() => {
    const set = new Set(employees.map((e) => e.department).filter(Boolean));
    return [...set].map((d) => ({ value: d, label: d }));
  }, [employees]);
  const employeeOptions = useMemo(
    () => employees.map((e) => ({ value: e.id, label: e.name })),
    [employees]
  );

  useEffect(() => {
    setLoading(true);
    api
      .get("/admin/performance", { params: filters })
      .then((res) => setRows(res.data))
      .finally(() => setLoading(false));
  }, [filters]);

  function setFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  async function handleExport() {
    await downloadCsv("/admin/reports/performance", filters, "performance_report.csv");
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold text-ink">Performance</h1>
        <button
          onClick={handleExport}
          className="rounded-xl border border-border bg-white text-ink text-sm font-medium px-4 py-2"
        >
          Export CSV
        </button>
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
          <FilterSelect label="Department" value={filters.department} onChange={(v) => setFilter("department", v)} options={departmentOptions} />
          <FilterSelect label="Status" value={filters.status} onChange={(v) => setFilter("status", v)} options={STATUS_OPTIONS} />
        </div>
      </Card>

      <Card className="!p-0 overflow-x-auto">
        <table className="w-full text-sm min-w-[700px]">
          <thead>
            <tr className="border-b border-border text-left text-xs text-slate-muted">
              <th className="px-4 py-3 font-medium">Employee</th>
              <th className="px-4 py-3 font-medium">Department</th>
              <th className="px-4 py-3 font-medium">Work date</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Submitted at</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-muted">
                  Loading…
                </td>
              </tr>
            ) : rows?.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-muted">
                  No performance records match these filters.
                </td>
              </tr>
            ) : (
              rows?.map((r) => (
                <tr key={`${r.employee_id}-${r.work_date}`} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-medium text-ink">{r.employee_name}</td>
                  <td className="px-4 py-3 text-slate-muted">{r.department || "--"}</td>
                  <td className="px-4 py-3">{formatDate(r.work_date)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-3 font-mono text-slate-muted">
                    {r.submitted_at ? formatTime(r.submitted_at) : "--"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
