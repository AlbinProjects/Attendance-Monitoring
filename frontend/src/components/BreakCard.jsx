import { useEffect, useMemo, useState } from "react";
import api from "../services/api";
import { useToast } from "../context/ToastContext";
import { formatDuration, formatTime } from "../utils/formatters";

const TYPES = [
  ["tea", "Tea Break"],
  ["lunch", "Lunch Break"],
  ["evening", "Evening Break"],
]; 

const EMPTY = {
  total_break_seconds: 0,
  active_break: null,
  sessions: [],
  used_break_types: [],
  available_break_types: ["tea", "lunch", "evening"],
};

export default function BreakCard({ breakData, canStart = false, onChanged }) {
  const { showToast } = useToast();
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [localData, setLocalData] = useState(breakData || EMPTY);

  useEffect(() => {
    setLocalData(breakData || EMPTY);
  }, [breakData]);

  useEffect(() => {
    if (!localData?.active_break) return undefined;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [localData?.active_break]);

  const active = localData?.active_break;
  const activeSeconds = useMemo(() => {
    if (!active?.started_at) return 0;
    return Math.max(0, Math.floor((now - new Date(active.started_at).getTime()) / 1000));
  }, [active, now]);

  const used = new Set(localData?.used_break_types || []);

  async function refreshBreaks() {
    try {
      const res = await api.get("/breaks/today", { params: { _ts: Date.now() } });
      setLocalData(res.data || EMPTY);
      return res.data;
    } catch (_) {
      return null;
    }
  }

  async function start(type) {
    if (!canStart || busy || active || used.has(type)) return;
    setBusy(true);
    try {
      const res = await api.post("/breaks/start", { break_type: type });
      const row = res.data;
      const sessions = [...(localData.sessions || []), row];
      setLocalData({
        ...localData,
        active_break: row,
        sessions,
        used_break_types: [...new Set([...(localData.used_break_types || []), type])],
        available_break_types: TYPES.map(([value]) => value).filter((value) => value !== type && !used.has(value)),
      });
      setNow(Date.now());
      showToast(`${labelFor(type)} started.`);
      onChanged?.();
    } catch (err) {
      // Recover immediately from stale UI state (e.g. a previous request
      // succeeded while the dashboard was still refreshing).
      const latest = await refreshBreaks();
      if (err?.response?.status === 409 && latest?.active_break) {
        showToast(`${labelFor(latest.active_break.break_type)} is already in progress.`, "error");
      } else {
        showToast(err?.response?.data?.detail || "Couldn't start break.", "error");
      }
    } finally {
      setBusy(false);
    }
  }

  async function end() {
    if (busy || !active) return;
    setBusy(true);
    try {
      const res = await api.post("/breaks/end");
      const row = res.data;
      const sessions = (localData.sessions || []).map((item) => item.id === row.id ? { ...item, ended_at: row.ended_at } : item);
      const total = sessions.reduce((sum, item) => {
        const start = new Date(item.started_at).getTime();
        const finish = item.ended_at ? new Date(item.ended_at).getTime() : Date.now();
        return sum + Math.max(0, Math.floor((finish - start) / 1000));
      }, 0);
      setLocalData({ ...localData, active_break: null, sessions, total_break_seconds: total });
      showToast("Break ended.");
      onChanged?.();
    } catch (err) {
      const latest = await refreshBreaks();
      if (err?.response?.status === 409 && latest && !latest.active_break) {
        showToast("Break was already ended.");
      } else {
        showToast(err?.response?.data?.detail || "Couldn't end break.", "error");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!localData) return null;

  return (
    <div className="rounded-2xl border border-border bg-white p-5 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-slate-muted">Breaks</p>
          <p className="font-semibold text-ink mt-1">
            {active ? `${labelFor(active.break_type)} in progress` : canStart ? "Take a break" : "Breaks available after check-in"}
          </p>
        </div>
        <span className="text-xs text-slate-muted font-mono">Today: {formatDuration(localData.total_break_seconds || 0)}</span>
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
          {TYPES.map(([value, label]) => {
            const alreadyUsed = used.has(value);
            return (
              <button
                key={value}
                disabled={busy || !canStart || alreadyUsed}
                onClick={() => start(value)}
                title={alreadyUsed ? `${label} already used today` : undefined}
                className="rounded-xl border border-border px-3 py-2.5 text-xs font-medium text-ink hover:bg-surface disabled:opacity-50"
              >
                {alreadyUsed ? `${label} ✓` : label}
              </button>
            );
          })}
        </div>
      )}

      {!active && !canStart && <p className="mt-3 text-xs text-slate-muted">Check in first to start a Tea, Lunch, or Evening break.</p>}
      {!active && canStart && <p className="mt-3 text-xs text-slate-muted">Each break type can be used once per day. You may take Tea, Lunch, and Evening breaks separately.</p>}

      {localData.sessions?.length > 0 && (
        <div className="mt-4 pt-3 border-t border-border space-y-1.5">
          {localData.sessions.map((row) => (
            <div key={row.id} className="flex items-center justify-between text-xs">
              <span className="text-slate-muted">{labelFor(row.break_type)}</span>
              <span className="font-mono text-ink">{formatTime(row.started_at)} → {row.ended_at ? formatTime(row.ended_at) : "now"}</span>
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
