/**
 * All timestamps arrive from the backend already computed in the office
 * timezone (see backend README "Attendance timezone") — these helpers only
 * format for display, they never recompute business logic on the client.
 */

export function formatTime(isoString) {
  if (!isoString) return "--";
  const d = new Date(isoString);
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function formatDate(isoDateOrString, opts = {}) {
  if (!isoDateOrString) return "--";
  const d = new Date(isoDateOrString.length === 10 ? `${isoDateOrString}T00:00:00` : isoDateOrString);
  return d.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: opts.withYear ? "numeric" : undefined,
  });
}

export function formatDuration(totalSeconds) {
  if (totalSeconds == null) return "--";
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.round((totalSeconds % 3600) / 60);
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

export function isToday(isoDate) {
  const today = new Date().toISOString().slice(0, 10);
  return isoDate === today;
}

export function isYesterday(isoDate) {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  const yesterday = d.toISOString().slice(0, 10);
  return isoDate === yesterday;
}
