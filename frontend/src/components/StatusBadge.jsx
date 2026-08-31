const STATUS_STYLES = {
  // Attendance
  present: { label: "Present", cls: "bg-brand-tint text-brand-dark" },
  late: { label: "Late", cls: "bg-amber-tint text-amber" },
  absent: { label: "Absent", cls: "bg-danger-tint text-danger" },
  half_day: { label: "Half day", cls: "bg-neutral2-tint text-neutral2" },
  manual: { label: "Manual entry", cls: "bg-neutral2-tint text-neutral2" },

  // Performance
  not_available: { label: "Not available yet", cls: "bg-surface text-slate-muted" },
  available: { label: "Available", cls: "bg-amber-tint text-amber" },
  submitted: { label: "Submitted", cls: "bg-brand-tint text-brand-dark" },
  missing: { label: "Missing", cls: "bg-danger-tint text-danger" },
  backdated: { label: "Backdated", cls: "bg-neutral2-tint text-neutral2" },
};

export default function StatusBadge({ status, className = "" }) {
  const style = STATUS_STYLES[status] || { label: status, cls: "bg-surface text-slate-muted" };
  return (
    <span
      className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${style.cls} ${className}`}
    >
      {style.label}
    </span>
  );
}
