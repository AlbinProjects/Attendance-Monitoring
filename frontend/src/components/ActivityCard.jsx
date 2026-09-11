import Card from "./Card";
import { formatDuration } from "../utils/formatters";

/**
 * Deliberately factual, not alarming — this reflects README's guidance
 * that the feature should never feel like invasive surveillance, and that
 * inactivity here means "no detected browser activity", not "not
 * working" (the employee could be in a meeting, reading paper documents,
 * etc.). Copy is careful not to overclaim.
 */
export default function ActivityCard({ activity, desktopActivity }) {
  if (!activity?.checked_in) return null;

  return (
    <Card>
      <p className="text-xs uppercase tracking-wide text-slate-muted mb-3">Today’s session</p>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <p className="text-slate-muted">Active time</p>
          <p className="font-mono text-lg mt-0.5 text-ink">{formatDuration(activity.active_session_seconds)}</p>
        </div>
        <div>
          <p className="text-slate-muted">Inactivity</p>
          <p className="font-mono text-lg mt-0.5 text-ink">{formatDuration(activity.counted_inactivity_seconds)}</p>
        </div>
      </div>
      <p className="text-xs text-slate-muted mt-3 leading-relaxed">
        Browser activity plus privacy-safe desktop work activity are used. No keystrokes,
        screenshots, window contents, URLs, source code, or document contents are collected.
      </p>
      <p className="text-xs mt-2 leading-relaxed">
        <span className={desktopActivity?.connected ? "text-brand-dark" : "text-amber"}>
          {desktopActivity?.connected
            ? "✓ Desktop work activity agent connected"
            : "Desktop activity agent not connected — work outside the browser may be counted as inactivity."}
        </span>
      </p>
    </Card>
  );
}
