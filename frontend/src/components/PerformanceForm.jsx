import { useState } from "react";

const FIELDS = [
  { name: "performance_text", label: "What did you work on?", rows: 3 },
  { name: "completed_tasks", label: "Tasks completed", rows: 3 },
  { name: "pending_tasks", label: "Pending tasks", rows: 2 },
  { name: "blockers", label: "Issues / blockers", rows: 2 },
  { name: "additional_notes", label: "Additional notes", rows: 2 },
];

export default function PerformanceForm({ onSubmit, submitting, submitLabel = "Submit performance" }) {
  const [values, setValues] = useState({
    performance_text: "",
    completed_tasks: "",
    pending_tasks: "",
    blockers: "",
    additional_notes: "",
  });

  function update(name, value) {
    setValues((prev) => ({ ...prev, [name]: value }));
  }

  function handleSubmit(e) {
    e.preventDefault();
    onSubmit(values);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {FIELDS.map(({ name, label, rows }) => (
        <div key={name}>
          <label className="block text-sm font-medium text-ink mb-1.5">{label}</label>
          <textarea
            rows={rows}
            value={values[name]}
            onChange={(e) => update(name, e.target.value)}
            className="w-full rounded-xl border border-border bg-white px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand/40 focus:border-brand resize-none"
          />
        </div>
      ))}
      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-xl bg-brand text-white font-medium py-3.5 active:scale-[0.99] transition-transform disabled:opacity-60"
      >
        {submitting ? "Submitting…" : submitLabel}
      </button>
    </form>
  );
}
