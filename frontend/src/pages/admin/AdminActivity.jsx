import { useEffect, useMemo, useState } from "react";
import api from "../../services/api";
import Card from "../../components/Card";
import FilterSelect from "../../components/admin/FilterSelect";
import { downloadCsv } from "../../utils/exportCsv";
import { formatDate, formatTime, formatDuration } from "../../utils/formatters";

const FLAG_OPTIONS = [
  { value: "true", label: "Flagged" },
  { value: "false", label: "Not flagged" },
];

export default function AdminActivity() {
  const [employees, setEmployees] = useState([]);
  const [rows, setRows] = useState(null);
  const [filters, setFilters] = useState({});
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState(null);
  const [periods, setPeriods] = useState(null);

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
      .get("/admin/activity", { params: filters })
      .then((res) => setRows(res.data))
      .finally(() => setLoading(false));
  }, [filters]);

  function setFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  async function toggleExpand(row) {
    if (expandedId === row.attendance_id) {
      setExpandedId(null);
      setPeriods(null);
      return;
    }
    setExpandedId(row.attendance_id);
    setPeriods(null);
    const res = await api.get(`/admin/activity/${row.attendance_id}/periods`);
    setPeriods(res.data);
  }

  async function handleExport() {
    await downloadCsv("/admin/reports/activity", filters, "activity_report.csv");
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold text-ink">Activity</h1>
        <button
          onClick={handleExport}
          className="rounded-xl border border-border bg-white text-ink text-sm font-medium px-4 py-2"
        >
          Export CSV
        </button>
      </div>
      <p className="text-sm text-slate-muted -mt-2">
        Reflects browser activity only — not a measure of productivity. Click a row to see its
        individual inactivity periods.
      </p>

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
          <FilterSelect label="Flag" value={filters.flag} onChange={(v) => setFilter("flag", v)} options={FLAG_OPTIONS} />
        </div>
      </Card>

      <Card className="!p-0 overflow-x-auto">
        <table className="w-full text-sm min-w-[800px]">
          <thead>
            <tr className="border-b border-border text-left text-xs text-slate-muted">
              <th className="px-4 py-3 font-medium">Employee</th>
              <th className="px-4 py-3 font-medium">Check-in</th>
              <th className="px-4 py-3 font-medium">Check-out</th>
              <th className="px-4 py-3 font-medium">Total session</th>
              <th className="px-4 py-3 font-medium">Counted inactivity</th>
              <th className="px-4 py-3 font-medium">Active</th>
              <th className="px-4 py-3 font-medium">Flag</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-muted">
                  Loading…
                </td>
              </tr>
            ) : rows?.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-slate-muted">
                  No activity records match these filters.
                </td>
              </tr>
            ) : (
              rows?.map((r) => (
                <>
                  <tr
                    key={r.attendance_id}
                    onClick={() => toggleExpand(r)}
                    className="border-b border-border last:border-0 cursor-pointer hover:bg-surface"
                  >
                    <td className="px-4 py-3 font-medium text-ink">
                      {r.employee_name}
                      <span className="text-slate-muted font-normal ml-2">{formatDate(r.attendance_date)}</span>
                    </td>
                    <td className="px-4 py-3 font-mono">{formatTime(r.check_in)}</td>
                    <td className="px-4 py-3 font-mono">{formatTime(r.check_out)}</td>
                    <td className="px-4 py-3 font-mono">{formatDuration(r.total_session_seconds)}</td>
                    <td className="px-4 py-3 font-mono">{formatDuration(r.counted_inactivity_seconds)}</td>
                    <td className="px-4 py-3 font-mono">{formatDuration(r.active_session_seconds)}</td>
                    <td className="px-4 py-3">
                      {r.flagged ? (
                        <span className="text-danger text-xs font-medium">⚠️ Flagged</span>
                      ) : (
                        <span className="text-slate-muted text-xs">Normal</span>
                      )}
                    </td>
                  </tr>
                  {expandedId === r.attendance_id && (
                    <tr className="bg-surface">
                      <td colSpan={7} className="px-4 py-3">
                        {periods === null ? (
                          <p className="text-xs text-slate-muted">Loading periods…</p>
                        ) : periods.length === 0 ? (
                          <p className="text-xs text-slate-muted">No inactivity periods recorded.</p>
                        ) : (
                          <div className="space-y-1.5">
                            {periods.map((p) => (
                              <div key={p.id} className="flex items-center justify-between text-xs">
                                <span className="font-mono text-slate-muted">
                                  {formatTime(p.started_at)} → {formatTime(p.ended_at)}
                                </span>
                                <span className="font-mono text-ink">
                                  {formatDuration(p.counted_duration_seconds)} counted
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </td>
                    </tr>
                  )}
                </>
              ))
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
