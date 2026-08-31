import { useState } from "react";

const ROLES = ["employee", "admin", "super_admin"];
const inputCls =
  "w-full border border-border rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand disabled:opacity-60";

export default function EmployeeForm({ initial, mode, onSubmit, submitting }) {
  const [values, setValues] = useState({
    employee_code: initial?.employee_code || "",
    name: initial?.name || "",
    email: initial?.email || "",
    department: initial?.department || "",
    designation: initial?.designation || "",
    role: initial?.role || "employee",
    joining_date: initial?.joining_date || "",
    is_active: initial?.is_active ?? true,
  });

  function update(field, value) {
    setValues((prev) => ({ ...prev, [field]: value }));
  }

  function handleSubmit(e) {
    e.preventDefault();
    onSubmit(values);
  }

  const isEdit = mode === "edit";

  return (
    <form onSubmit={handleSubmit} className="space-y-3.5">
      <Field label="Employee code">
        <input
          required
          disabled={isEdit}
          value={values.employee_code}
          onChange={(e) => update("employee_code", e.target.value)}
          className={inputCls}
        />
      </Field>
      <Field label="Full name">
        <input
          required
          value={values.name}
          onChange={(e) => update("name", e.target.value)}
          className={inputCls}
        />
      </Field>
      <Field label="Email">
        <input
          required
          type="email"
          disabled={isEdit}
          value={values.email}
          onChange={(e) => update("email", e.target.value)}
          className={inputCls}
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Department">
          <input
            value={values.department}
            onChange={(e) => update("department", e.target.value)}
            className={inputCls}
          />
        </Field>
        <Field label="Designation">
          <input
            value={values.designation}
            onChange={(e) => update("designation", e.target.value)}
            className={inputCls}
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Role">
          <select value={values.role} onChange={(e) => update("role", e.target.value)} className={inputCls}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r.replace("_", " ")}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Joining date">
          <input
            type="date"
            value={values.joining_date}
            onChange={(e) => update("joining_date", e.target.value)}
            className={inputCls}
          />
        </Field>
      </div>

      {isEdit && (
        <label className="flex items-center gap-2 text-sm text-ink">
          <input
            type="checkbox"
            checked={values.is_active}
            onChange={(e) => update("is_active", e.target.checked)}
          />
          Account active
        </label>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-xl bg-brand text-white font-medium py-3 mt-2 disabled:opacity-60"
      >
        {submitting ? "Saving…" : isEdit ? "Save changes" : "Create employee"}
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
