export default function FilterSelect({ label, value, onChange, options }) {
  return (
    <label className="text-xs text-slate-muted flex flex-col gap-1">
      {label}
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || undefined)}
        className="rounded-lg border border-border bg-white px-2.5 py-1.5 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-brand/40"
      >
        <option value="">All</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}
