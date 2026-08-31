export default function LoadingScreen({ label = "Loading…" }) {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="h-6 w-6 rounded-full border-2 border-border border-t-brand animate-spin" />
        <p className="text-sm text-slate-muted">{label}</p>
      </div>
    </div>
  );
}
