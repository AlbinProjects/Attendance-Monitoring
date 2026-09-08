import { useEffect, useMemo, useState } from "react";
import api from "../services/api";
import { useToast } from "../context/ToastContext";
import { formatDuration, formatTime } from "../utils/formatters";

const TYPES = [
  ["tea", "Tea Break"],
  ["lunch", "Lunch Break"],
  ["evening", "Evening Break"],
];

export default function BreakCard({ breakData, canStart = false, onChanged }) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!breakData?.active_break) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [breakData?.active_break]);

  const active = breakData?.active_break;
  const activeSeconds = useMemo(() => {
    if (!active?.started_at) return 0;
    return Math.max(0, Math.floor((now - new Date(active.started_at).getTime()) / 1000));
  }, [active, now]);

  async function start(type) {
    if (!canStart) return;
    setBusy(true);
    try {
      await api.post("/breaks/start", { break_type: type });
      showToast(`${labelFor(type)} started.`);
      onChanged?.();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't start break.", "error");
    } finally {
      setBusy(false);
    }
  }

  async function end() {
    setBusy(true);
    try {
      await api.post("/breaks/end");
      showToast("Break ended.");
      onChanged?.();
    } catch (err) {
      showToast(err?.response?.data?.detail || "Couldn't end break.", "error");
    } finally {
      setBusy(false);
    }
  }

  if (!breakData) return null;

  return (
    <div className="rounded-2xl border border-border bg-white p-5 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-muted">Breaks</p>
          <p className="font-semibold text-ink mt-1">
            {active ? `${labelFor(active.break_type)} in progress` : canStart ? "Take a break" : "Breaks available after check-in"}
          </p>
        </div>
        <span className="text-xs text-slate-muted font-mono">
          Today: {formatDuration(breakData.total_break_seconds || 0)}
        </span>
      </div>

      {active ? (
        <div className="mt-4 flex items-center justify-between gap-3">
          <div>
            <p className="font-mono text-xl tabular-nums">{formatDuration(activeSeconds)}</p>
            <p className="text-xs text-slate-muted mt-1">Started {formatTime(active.started_at)}</p>
          </div>
          <button disabled={busy} onClick={end} className="rounded-xl bg-ink text-white px-4 py-2.5 text-sm font-medium disabled:opacity-60">
            {busy ? "Please wait…" : "End Break"}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-3 gap-2 mt-4">
          {TYPES.map(([value, label]) => (
            <button key={value} disabled={busy || !canStart} onClick={() => start(value)} className="rounded-xl border border-border px-3 py-2.5 text-xs font-medium text-ink hover:bg-surface disabled:opacity-60">
              {label}
            </button>
          ))}
        </div>
      )}
      {!active && !canStart && (
        <p className="mt-3 text-xs text-slate-muted">Check in first to start a Tea, Lunch, or Evening break.</p>
      )}

      {breakData.sessions?.length > 0 && (
        <div className="mt-4 pt-3 border-t border-border space-y-1.5">
          {breakData.sessions.map((row) => (
            <div key={row.id} className="flex items-center justify-between text-xs">
              <span className="text-slate-muted">{labelFor(row.break_type)}</span>
              <span className="font-mono text-ink">
                {formatTime(row.started_at)} → {row.ended_at ? formatTime(row.ended_at) : "now"}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function labelFor(type) {
  return TYPES.find(([value]) => value === type)?.[1] || type;
}
