import Card from "./Card";

export default function StatCard({ label, value, tone = "default", onClick, active = false }) {
  const toneCls =
    tone === "danger"
      ? "text-danger"
      : tone === "amber"
      ? "text-amber"
      : tone === "brand"
      ? "text-brand-dark"
      : "text-ink";

  const interactiveCls = onClick
    ? "cursor-pointer transition-shadow hover:shadow-md focus-within:ring-2 focus-within:ring-brand/30"
    : "";
  const activeCls = active ? "ring-2 ring-brand/30" : "";

  return (
    <Card className={`!p-4 ${interactiveCls} ${activeCls}`} onClick={onClick}>
      <p className="text-xs text-slate-muted">{label}</p>
      <p className={`font-mono text-2xl mt-1 ${toneCls}`}>{value}</p>
      {onClick && <p className="text-[11px] text-slate-muted mt-1">Click to view details</p>}
    </Card>
  );
}
