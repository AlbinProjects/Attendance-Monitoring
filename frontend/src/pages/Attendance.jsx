import { useEffect, useState } from "react";
import api from "../services/api";
import Card from "../components/Card";
import StatusBadge from "../components/StatusBadge";
import LoadingScreen from "../components/LoadingScreen";
import { formatDate, formatTime } from "../utils/formatters";

export default function Attendance() {
  const [history, setHistory] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .get("/attendance/history")
      .then((res) => setHistory(res.data))
      .catch(() => setError("Couldn't load your attendance history."));
  }, []);

  if (error) {
    return <p className="text-sm text-danger">{error}</p>;
  }

  if (!history) return <LoadingScreen />;

  if (history.length === 0) {
    return (
      <Card className="text-center py-10">
        <p className="text-sm text-slate-muted">
          No attendance recorded yet.
        </p>
      </Card>
    );
  }

  const months = groupByMonth(history, "attendance_date");

  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold text-ink">
        Attendance
      </h1>

      {months.map(({ key, label, rows }) => (
        <section key={key}>
          <h2 className="text-sm font-semibold text-ink mb-3">
            {label}
          </h2>

          <div className="space-y-2.5">
            {rows.map((row) => (
              <Card key={row.id} padded className="!p-4">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-ink">
                    {formatDate(row.attendance_date, {
                      withYear: true,
                    })}
                  </p>

                  <StatusBadge status={row.status} />
                </div>

                <div className="grid grid-cols-2 gap-3 mt-3 text-sm">
                  <div>
                    <p className="text-slate-muted text-xs">
                      Check-in
                    </p>
                    <p className="font-mono mt-0.5">
                      {formatTime(row.check_in)}
                    </p>
                  </div>

                  <div>
                    <p className="text-slate-muted text-xs">
                      Check-out
                    </p>
                    <p className="font-mono mt-0.5">
                      {formatTime(row.check_out)}
                    </p>
                  </div>
                </div>

                {row.status === "manual" && row.reason && (
                  <p className="text-xs text-neutral2 mt-3 bg-neutral2-tint rounded-lg px-2.5 py-1.5">
                    Marked by admin: {row.reason}
                  </p>
                )}
              </Card>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function groupByMonth(rows, dateField) {
  const groups = new Map();

  for (const row of rows) {
    const value = row[dateField];
    if (!value) continue;

    const [year, month] = value.split("-");

    const key = `${year}-${month}`;

    if (!groups.has(key)) {
      const date = new Date(
        Number(year),
        Number(month) - 1,
        1
      );

      groups.set(key, {
        key,
        label: date.toLocaleDateString(undefined, {
          month: "long",
          year: "numeric",
        }),
        rows: [],
      });
    }

    groups.get(key).rows.push(row);
  }

  return Array.from(groups.values()).sort((a, b) =>
    b.key.localeCompare(a.key)
  );
}
