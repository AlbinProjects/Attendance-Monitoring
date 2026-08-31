import { useCallback, useEffect, useMemo, useState } from "react";
import api from "../../services/api";
import { useToast } from "../../context/ToastContext";
import Card from "../../components/Card";
import StatusBadge from "../../components/StatusBadge";
import FilterSelect from "../../components/admin/FilterSelect";
import Modal from "../../components/Modal";
import ManualAttendanceForm from "../../components/admin/ManualAttendanceForm";
import { downloadCsv } from "../../utils/exportCsv";
import { formatDate, formatTime, formatDuration } from "../../utils/formatters";

const STATUS_OPTIONS = [
  { value: "present", label: "Present" },
  { value: "late", label: "Late" },
  { value: "absent", label: "Absent" },
  { value: "half_day", label: "Half day" },
  { value: "manual", label: "Manual" },
];
const SOURCE_OPTIONS = [
  { value: "gps", label: "GPS" },
  { value: "wifi", label: "WiFi (historical)" },
  { value: "admin", label: "Admin" },
];
const FLAG_OPTIONS = [
  { value: "true", label: "Flagged" },
  { value: "false", label: "Not flagged" },
];

export default function AdminAttendance() {
  const { showToast } = useToast();
  const [employees, setEmployees] = useState([]);
  const [rows, setRows] = useState(null);
  const [filters, setFilters] = useState({});
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // { mode: 'create' | 'correct', row? }
  const [submitting, setSubmitting] = useState(false);

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

  const loadRows = useCallback(() => {
    setLoading(true);
    return api
      .get("/admin/attendance", { params: filters })
      .then((res) => setRows(res.data))
      .finally(() => setLoading(false));
  }, [filters]);

  useEffect(() => {
    loadRows();
  }, [loadRows]);

  function setFilter(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  async function handleCreateManual(values) {
    setSubmitting(true);
    try {
      await api.post("/admin/attendance/manual", values);
      showToast("Manual attendance recorded.");
      setModal(null);
      loadRows();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't record attendance.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCorrect(attendanceId, values) {
    setSubmitting(true);
    try {
      await api.put(`/admin/attendance/${attendanceId}`, values);
      showToast("Attendance corrected.");
      setModal(null);
      loadRows();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't correct attendance.", "error");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleExport() {
    await downloadCsv("/admin/reports/attendance", filters, "attendance_report.csv");
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-semibold text-ink">Attendance</h1>
        <div className="flex gap-2">
          <button
            onClick={handleExport}
            className="rounded-xl border border-border bg-white text-ink text-sm font-medium px-4 py-2"
          >
            Export CSV
          </button>
          <button
            onClick={() => setModal({ mode: "create" })}
            className="rounded-xl bg-ink text-white text-sm font-medium px-4 py-2"
          >
            + Manual attendance
          </button>
        </div>
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
          <FilterSelect label="Source" value={filters.source} onChange={(v) => setFilter("source", v)} options={SOURCE_OPTIONS} />
          <FilterSelect label="Inactivity" value={filters.inactivity_flag} onChange={(v) => setFilter("inactivity_flag", v)} options={FLAG_OPTIONS} />
        </div>
      </Card>

      <Card className="!p-0 overflow-x-auto">
        <table className="w-full text-sm min-w-[950px]">
          <thead>
            <tr className="border-b border-border text-left text-xs text-slate-muted">
              <th className="px-4 py-3 font-medium">Employee</th>
              <th className="px-4 py-3 font-medium">Department</th>
              <th className="px-4 py-3 font-medium">Date</th>
              <th className="px-4 py-3 font-medium">Check-in</th>
              <th className="px-4 py-3 font-medium">Check-out</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Source</th>
              <th className="px-4 py-3 font-medium">Active</th>
              <th className="px-4 py-3 font-medium">Inactivity</th>
              <th className="px-4 py-3 font-medium">Flag</th>
              <th className="px-4 py-3 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={11} className="px-4 py-8 text-center text-slate-muted">
                  Loading…
                </td>
              </tr>
            ) : rows?.length === 0 ? (
              <tr>
                <td colSpan={11} className="px-4 py-8 text-center text-slate-muted">
                  No attendance records match these filters.
                </td>
              </tr>
            ) : (
              rows?.map((r) => (
                <tr key={r.id} className="border-b border-border last:border-0">
                  <td className="px-4 py-3 font-medium text-ink">{r.employee_name}</td>
                  <td className="px-4 py-3 text-slate-muted">{r.department || "--"}</td>
                  <td className="px-4 py-3">{formatDate(r.attendance_date)}</td>
                  <td className="px-4 py-3 font-mono">{formatTime(r.check_in)}</td>
                  <td className="px-4 py-3 font-mono">{formatTime(r.check_out)}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-muted">{formatSourceLabel(r.check_in_source)}</td>
                  <td className="px-4 py-3 font-mono">{formatDuration(r.active_session_seconds)}</td>
                  <td className="px-4 py-3 font-mono">{formatDuration(r.counted_inactivity_seconds)}</td>
                  <td className="px-4 py-3">
                    {r.inactivity_flag ? (
                      <span className="text-danger text-xs font-medium">⚠️ Flagged</span>
                    ) : (
                      <span className="text-slate-muted text-xs">Normal</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => setModal({ mode: "correct", row: r })}
                      className="text-brand text-xs font-medium"
                    >
                      Correct
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>

      {modal?.mode === "create" && (
        <Modal title="Manual attendance" onClose={() => setModal(null)}>
          <ManualAttendanceForm
            mode="create"
            employees={employees}
            onSubmit={handleCreateManual}
            submitting={submitting}
          />
        </Modal>
      )}

      {modal?.mode === "correct" && (
        <Modal title={`Correct — ${modal.row.employee_name}`} onClose={() => setModal(null)}>
          <ManualAttendanceForm
            mode="correct"
            row={modal.row}
            onSubmit={(values) => handleCorrect(modal.row.id, values)}
            submitting={submitting}
          />
        </Modal>
      )}
    </div>
  );
}

function formatSourceLabel(source) {
  if (!source) return "--";
  if (source === "gps") return "GPS";
  if (source === "wifi") return "WiFi";
  if (source === "admin") return "Admin";
  return source;
}
