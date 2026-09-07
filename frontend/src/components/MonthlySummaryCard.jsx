import Card from "./Card";

const ROWS = [
  { key: "present", label: "Present", dot: "bg-brand" },
  { key: "late", label: "Late", dot: "bg-amber" },
  { key: "absent", label: "Absent", dot: "bg-danger" },
  { key: "half_day", label: "Half day", dot: "bg-neutral2" },
];

export default function MonthlySummaryCard({ monthly }) {
  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <p className="text-xs uppercase tracking-wide text-slate-muted">This month</p>
        <p className="font-mono text-lg text-ink">{monthly.percentage}%</p>
      </div>
      <div className="space-y-2.5">
        {ROWS.map(({ key, label, dot }) => (
          <div key={key} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 text-ink">
              <span className={`h-2 w-2 rounded-full ${dot}`} />
              {label}
            </span>
            <span className="font-mono text-slate-muted">{monthly.counts[key]}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}
