import Card from "./Card";

export default function StatCard({ label, value, tone = "default" }) {
  const toneCls =
    tone === "danger"
      ? "text-danger"
      : tone === "amber"
      ? "text-amber"
      : tone === "brand"
      ? "text-brand-dark"
      : "text-ink";

  return (
    <Card className="!p-4">
      <p className="text-xs text-slate-muted">{label}</p>
      <p className={`font-mono text-2xl mt-1 ${toneCls}`}>{value}</p>
    </Card>
  );
}
