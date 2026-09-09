import { useEffect, useMemo, useState } from "react";
import { formatDuration, formatTime } from "../utils/formatters";
import StatusBadge from "./StatusBadge";

/*
 * Physical-time-clock style punch card with a mandatory checkout confirmation.
 * Checkout always asks for confirmation, including after the full 8-hour
 * target. Once four net work hours are complete, the employee can choose to
 * request half-day leave; the actual attendance checkout still happens first
 * and the half-day request then goes to Admin/Super Admin approval.
 */
export default function PunchCard({ today, breakData, punching, statusLabel, onPunch }) {
  const [now, setNow] = useState(new Date());
  const [justStamped, setJustStamped] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const hasCheckedIn = !!today?.check_in;
  const hasCheckedOut = !!today?.check_out;
  const activeBreak = breakData?.active_break;

  const netWorkedSeconds = useMemo(() => {
    if (!today?.check_in) return 0;
    const start = new Date(today.check_in).getTime();
    const end = today.check_out ? new Date(today.check_out).getTime() : now.getTime();
    const gross = Math.max(0, Math.floor((end - start) / 1000));
    let breakSeconds = Number(breakData?.total_break_seconds || 0);
    if (activeBreak?.started_at && !activeBreak?.ended_at && !today.check_out) {
      breakSeconds += Math.max(0, Math.floor((now.getTime() - new Date(activeBreak.started_at).getTime()) / 1000));
    }
    return Math.max(0, gross - breakSeconds);
  }, [today?.check_in, today?.check_out, breakData?.total_break_seconds, activeBreak, now]);

  const targetSeconds = 8 * 60 * 60;
  const halfDayEligible = hasCheckedIn && !hasCheckedOut && !activeBreak && netWorkedSeconds >= 4 * 60 * 60 && netWorkedSeconds < targetSeconds;
  const remainingSeconds = Math.max(0, targetSeconds - netWorkedSeconds);

  function handleClick() {
    if (!hasCheckedIn) {
      setJustStamped(true);
      setTimeout(() => setJustStamped(false), 250);
      onPunch();
      return;
    }
    if (hasCheckedOut) return;
    if (activeBreak) return;
    setConfirmOpen(true);
  }

  function confirmCheckout(requestHalfDay = false) {
    setConfirmOpen(false);
    setJustStamped(true);
    setTimeout(() => setJustStamped(false), 250);
    onPunch({ requestHalfDay });
  }

  const buttonLabel = !hasCheckedIn ? "Check in" : !hasCheckedOut ? "Check out" : "Done for today";

  return (
    <>
      <div className="rounded-2xl bg-ink text-white p-6 shadow-card">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs uppercase tracking-wide text-white/60">Today</p>
            <p className="font-mono text-3xl mt-1 tabular-nums">
              {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </p>
          </div>
          {today?.status && <StatusBadge status={today.status} className="!bg-white/10 !text-white" />}
        </div>

        <div className="grid grid-cols-2 gap-4 mt-5 text-sm">
          <div>
            <p className="text-white/50">Check-in</p>
            <p className="font-mono text-base mt-0.5">{formatTime(today?.check_in)}</p>
          </div>
          <div>
            <p className="text-white/50">Check-out</p>
            <p className="font-mono text-base mt-0.5">{formatTime(today?.check_out)}</p>
          </div>
        </div>

        <button
          onClick={handleClick}
          disabled={punching || hasCheckedOut}
          title={activeBreak ? "End your active break before checking out." : undefined}
          className={`mt-5 w-full rounded-xl py-4 text-base font-semibold transition-all active:scale-[0.98] disabled:opacity-50 disabled:active:scale-100 ${
            hasCheckedOut ? "bg-white/10 text-white/60" : "bg-brand text-white"
          } ${justStamped ? "animate-stamp" : ""}`}
        >
          {punching ? statusLabel || "Please wait…" : activeBreak && !hasCheckedOut ? "End break before check-out" : buttonLabel}
        </button>
      </div>

      {confirmOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="checkout-title">
          <div className="w-full max-w-md rounded-2xl bg-white p-5 shadow-2xl">
            <h2 id="checkout-title" className="text-lg font-semibold text-ink">Confirm check-out</h2>
            <p className="text-sm text-slate-muted mt-2">
              {netWorkedSeconds >= targetSeconds
                ? "You have completed the 8-hour work target. Are you sure you want to check out?"
                : `You have worked ${formatDuration(netWorkedSeconds)}. You still need ${formatDuration(remainingSeconds)} to reach 8 hours. Are you sure you want to check out?`}
            </p>

            <div className="mt-4 rounded-xl bg-surface px-3 py-3 text-sm">
              <div className="flex justify-between gap-3"><span className="text-slate-muted">Net work</span><strong>{formatDuration(netWorkedSeconds)}</strong></div>
              <div className="flex justify-between gap-3 mt-1"><span className="text-slate-muted">8-hour target</span><strong>{netWorkedSeconds >= targetSeconds ? "Completed" : `${formatDuration(remainingSeconds)} remaining`}</strong></div>
              <div className="flex justify-between gap-3 mt-1"><span className="text-slate-muted">Check-in</span><strong className="font-mono">{formatTime(today?.check_in)}</strong></div>
            </div>

            {halfDayEligible && (
              <div className="mt-4 rounded-xl border border-amber/30 bg-amber-tint p-3">
                <p className="text-sm font-medium text-amber">Half-day leave is available</p>
                <p className="text-xs text-slate-muted mt-1">You have completed at least 4 net work hours. Requesting half-day leave will require Admin/Super Admin approval before it is reflected as half-day leave on your attendance and calendar.</p>
              </div>
            )}

            <div className="flex flex-col gap-2 mt-5">
              {halfDayEligible && (
                <button onClick={() => confirmCheckout(true)} disabled={punching} className="w-full rounded-xl bg-amber px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">Request Half-Day Leave &amp; Check Out</button>
              )}
              <button onClick={() => confirmCheckout(false)} disabled={punching} className="w-full rounded-xl bg-ink px-4 py-3 text-sm font-semibold text-white disabled:opacity-50">Confirm Check-out</button>
              <button onClick={() => setConfirmOpen(false)} disabled={punching} className="w-full rounded-xl border border-border px-4 py-3 text-sm font-medium text-ink disabled:opacity-50">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
