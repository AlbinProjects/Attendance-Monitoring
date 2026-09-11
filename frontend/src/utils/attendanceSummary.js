/**
 * Aggregates attendance history into a current-month summary for display.
 * This is purely presentational — attendance_date strings already reflect
 * the office timezone's calendar date as computed by the backend (see
 * backend README "Attendance timezone"); we just group by the YYYY-MM
 * prefix of the device's current date, which is a reasonable
 * approximation for a summary card and not used for any business decision.
 */
export function computeMonthlySummary(historyRows) {
  const monthPrefix = new Date().toISOString().slice(0, 7); // "2026-08"
  const thisMonth = historyRows.filter((r) => r.attendance_date?.startsWith(monthPrefix));

  const counts = { present: 0, late: 0, absent: 0, half_day: 0, manual: 0 };
  for (const row of thisMonth) {
    if (row.status && counts[row.status] !== undefined) counts[row.status] += 1;
  }

  const markedDays = thisMonth.length;
  const presentLike = counts.present + counts.late + counts.half_day + counts.manual;
  const percentage = markedDays > 0 ? Math.round((presentLike / markedDays) * 100) : 0;

  return { counts, markedDays, percentage };
}
