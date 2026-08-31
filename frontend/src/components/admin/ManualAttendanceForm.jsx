import { useState } from "react";

const inputCls =
  "w-full border border-border rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand";

/**
 * Shared by two flows:
 *  - "create": Super Admin/Admin marks a brand-new exceptional attendance
 *    record (employee + date + times + reason).
 *  - "correct": adjusts an existing record's check-in/check-out (fields
 *    left blank keep their current value) — always requires a reason.
 */
export default function ManualAttendanceForm({ mode, employees, row, onSubmit, submitting }) {
  const isCreate = mode === "create";

  const [employeeId, setEmployeeId] = useState("");
  const [attendanceDate, setAttendanceDate] = useState("");
  const [checkInTime, setCheckInTime] = useState(isCreate ? "" : toTimeInput(row?.check_in));
  const [checkOutTime, setCheckOutTime] = useState(isCreate ? "" : toTimeInput(row?.check_out));
  const [reason, setReason] = useState("");

  function toTimeInput(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toTimeString().slice(0, 5);
  }

  function handleSubmit(e) {
    e.preventDefault();
    if (isCreate) {
      onSubmit({
        employee_id: employeeId,
        attendance_date: attendanceDate,
        check_in_time: checkInTime ? `${checkInTime}:00` : null,
        check_out_time: checkOutTime ? `${checkOutTime}:00` : null,
        reason,
      });
    } else {
      onSubmit({
        check_in_time: checkInTime ? `${checkInTime}:00` : null,
        check_out_time: checkOutTime ? `${checkOutTime}:00` : null,
        reason,
      });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3.5">
      {isCreate && (
        <>
          <Field label="Employee">
            <select
              required
              value={employeeId}
              onChange={(e) => setEmployeeId(e.target.value)}
              className={inputCls}
            >
              <option value="" disabled>
                Select an employee
              </option>
              {employees?.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.name} ({emp.employee_code})
                </option>
              ))}
            </select>
          </Field>
          <Field label="Date">
            <input
              required
              type="date"
              value={attendanceDate}
              onChange={(e) => setAttendanceDate(e.target.value)}
              className={inputCls}
            />
          </Field>
        </>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Field label="Check-in">
          <input type="time" value={checkInTime} onChange={(e) => setCheckInTime(e.target.value)} className={inputCls} />
        </Field>
        <Field label="Check-out">
          <input type="time" value={checkOutTime} onChange={(e) => setCheckOutTime(e.target.value)} className={inputCls} />
        </Field>
      </div>

      <Field label="Reason">
        <textarea
          required
          rows={3}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Company WiFi outage, forgot to check in…"
          className={`${inputCls} resize-none`}
        />
      </Field>

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-xl bg-brand text-white font-medium py-3 mt-1 disabled:opacity-60"
      >
        {submitting ? "Saving…" : isCreate ? "Mark full attendance" : "Save correction"}
      </button>
    </form>
  );
}

function Field({ label, children }) {
  return (
    <label className="block text-sm">
      <span className="block text-xs text-slate-muted mb-1">{label}</span>
      {children}
    </label>
  );
}
