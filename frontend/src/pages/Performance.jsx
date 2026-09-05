import { useCallback, useEffect, useState } from "react";
import api from "../services/api";
import { useToast } from "../context/ToastContext";
import Card from "../components/Card";
import StatusBadge from "../components/StatusBadge";
import LoadingScreen from "../components/LoadingScreen";
import PerformanceForm from "../components/PerformanceForm";
import { formatDate, formatTime } from "../utils/formatters";

export default function Performance() {
  const { showToast } = useToast();

  const [today, setToday] = useState(null);
  const [missing, setMissing] = useState(null);
  const [history, setHistory] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [showYesterdayForm, setShowYesterdayForm] = useState(false);

  const loadAll = useCallback(async () => {
    const [todayRes, missingRes, historyRes] = await Promise.all([
      api.get("/performance/today"),
      api.get("/performance/missing"),
      api.get("/performance/history"),
    ]);

    setToday(todayRes.data);
    setMissing(missingRes.data);
    setHistory(historyRes.data);
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  const yesterdayIso = (() => {
    const d = new Date();
    d.setDate(d.getDate() - 1);

    return [
      d.getFullYear(),
      String(d.getMonth() + 1).padStart(2, "0"),
      String(d.getDate()).padStart(2, "0"),
    ].join("-");
  })();

  const yesterdayIsMissing = missing?.some(
    (m) => m.work_date === yesterdayIso
  );

  const todayIsMissing = missing?.some(
    (m) => m.work_date === today?.work_date
  );

  async function handleSubmitToday(values) {
    setSubmitting(true);

    try {
      await api.post("/performance", values);
      showToast("Performance submitted.");
      await loadAll();
    } catch (err) {
      showToast(
        err?.response?.data?.detail ||
          "Couldn't submit. Please try again.",
        "error"
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSubmitYesterday(values) {
    setSubmitting(true);

    try {
      await api.post("/performance", {
        ...values,
        work_date: yesterdayIso,
      });

      showToast("Yesterday's performance submitted.");
      setShowYesterdayForm(false);
      await loadAll();
    } catch (err) {
      showToast(
        err?.response?.data?.detail ||
          "Couldn't submit. Please try again.",
        "error"
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (!today || !missing || !history) {
    return <LoadingScreen />;
  }

  const months = groupByMonth(history, "work_date");

  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold text-ink">
        Performance
      </h1>

      <TodaySection
        today={today}
        submitting={submitting}
        onSubmit={handleSubmitToday}
      />

      {yesterdayIsMissing && (
        <Card className="!bg-danger-tint !border-danger/20">
          <p className="text-sm font-medium text-danger">
            ⚠️ Yesterday’s performance is missing
          </p>

          <p className="text-xs text-danger/80 mt-1 mb-3">
            {formatDate(yesterdayIso, { withYear: true })}
          </p>

          {!showYesterdayForm ? (
            <button
              onClick={() => setShowYesterdayForm(true)}
              className="w-full rounded-xl bg-danger text-white font-medium py-2.5 text-sm"
            >
              Update yesterday
            </button>
          ) : (
            <div className="mt-2">
              <PerformanceForm
                onSubmit={handleSubmitYesterday}
                submitting={submitting}
                submitLabel="Submit for yesterday"
              />
            </div>
          )}
        </Card>
      )}

      <div>
        <p className="text-xs uppercase tracking-wide text-slate-muted mb-3">
          History
        </p>

        <div className="space-y-5">
          {months.map(({ key, label, rows }) => (
            <section key={key}>
              <h2 className="text-sm font-semibold text-ink mb-3">
                {label}
              </h2>

              <div className="space-y-2.5">
                {rows.map((row) => (
                  <Card
                    key={row.work_date}
                    padded
                    className="!p-4"
                  >
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-medium text-ink">
                        {formatDate(row.work_date, {
                          withYear: true,
                        })}
                      </p>

                      <StatusBadge status={row.status} />
                    </div>

                    {row.submitted_at && (
                      <p className="text-xs text-slate-muted mt-1.5">
                        Submitted {formatTime(row.submitted_at)}
                      </p>
                    )}
                  </Card>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
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

function TodaySection({ today, submitting, onSubmit }) {
  if (today.status === "not_available") {
    return (
      <Card className="text-center py-8">
        <p className="text-2xl mb-2">🔒</p>

        <p className="text-sm font-medium text-ink">
          Today’s performance isn’t available yet
        </p>

        <p className="text-xs text-slate-muted mt-1">
          Available from {formatTime(today.available_from)}
        </p>
      </Card>
    );
  }

  if (today.status === "submitted") {
    const record = today.record;

    return (
      <Card>
        <div className="flex items-center justify-between mb-3">
          <p className="text-sm font-medium text-ink">
            Today’s performance
          </p>

          <StatusBadge status="submitted" />
        </div>

        <dl className="space-y-3 text-sm">
          <Field
            label="What was worked on"
            value={record?.performance_text}
          />
          <Field
            label="Completed tasks"
            value={record?.completed_tasks}
          />
          <Field
            label="Pending tasks"
            value={record?.pending_tasks}
          />
          <Field
            label="Blockers"
            value={record?.blockers}
          />
          <Field
            label="Notes"
            value={record?.additional_notes}
          />
        </dl>
      </Card>
    );
  }

  return (
    <Card>
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm font-medium text-ink">
          Today’s performance
        </p>

        <StatusBadge status="available" />
      </div>

      <PerformanceForm
        onSubmit={onSubmit}
        submitting={submitting}
      />
    </Card>
  );
}

function Field({ label, value }) {
  if (!value) return null;

  return (
    <div>
      <dt className="text-xs text-slate-muted">
        {label}
      </dt>

      <dd className="text-ink mt-0.5 whitespace-pre-wrap">
        {value}
      </dd>
    </div>
  );
}
