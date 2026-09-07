import { useEffect, useState } from "react";
import { formatTime } from "../utils/formatters";
import StatusBadge from "./StatusBadge";

/**
 * The one deliberately bold element on the dashboard — everything else
 * stays quiet and functional. Styled after a physical time clock: a
 * monospace live clock face, a big tactile punch button, and a brief
 * "stamp" animation on action. See frontend README/design notes for the
 * rest of the token system.
 */
export default function PunchCard({ today, punching, statusLabel, onPunch }) {
  const [now, setNow] = useState(new Date());
  const [justStamped, setJustStamped] = useState(false);

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const hasCheckedIn = !!today?.check_in;
  const hasCheckedOut = !!today?.check_out;

  function handleClick() {
    setJustStamped(true);
    setTimeout(() => setJustStamped(false), 250);
    onPunch();
  }

  const buttonLabel = !hasCheckedIn ? "Check in" : !hasCheckedOut ? "Check out" : "Done for today";

  return (
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
        className={`mt-5 w-full rounded-xl py-4 text-base font-semibold transition-all active:scale-[0.98] disabled:opacity-50 disabled:active:scale-100 ${
          hasCheckedOut ? "bg-white/10 text-white/60" : "bg-brand text-white"
        } ${justStamped ? "animate-stamp" : ""}`}
      >
        {punching ? statusLabel || "Please wait…" : buttonLabel}
      </button>
    </div>
  );
}
