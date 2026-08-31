import Card from "./Card";
import { formatDuration } from "../utils/formatters";

/**
 * Deliberately factual, not alarming — this reflects README's guidance
 * that the feature should never feel like invasive surveillance, and that
 * inactivity here means "no detected browser activity", not "not
 * working" (the employee could be in a meeting, reading paper documents,
 * etc.). Copy is careful not to overclaim.
 */
export default function ActivityCard({ activity }) {
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
          <p className="text-slate-muted">System inactivity</p>
          <p className="font-mono text-lg mt-0.5 text-ink">{formatDuration(activity.counted_inactivity_seconds)}</p>
        </div>
      </div>
      <p className="text-xs text-slate-muted mt-3 leading-relaxed">
        Based on browser activity only — reading documents, meetings, or work outside
        this browser tab aren’t counted here.
      </p>
    </Card>
  );
}
