import { useMemo } from "react";

import { AttendanceException } from "../../lib/siteStatusService";
import { computeKpis } from "./kpi";

interface KpiCardProps {
  label: string;
  value: number | null;
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}

function KpiCard({ label, value, loading, error, onRetry }: KpiCardProps) {
  return (
    <div className="flex min-w-[140px] flex-col gap-1 rounded-lg border border-zinc-200 px-4 py-3 dark:border-zinc-800">
      <span className="text-xs font-medium text-zinc-500">{label}</span>
      {loading ? (
        <span className="h-7 w-10 animate-pulse rounded bg-zinc-200 dark:bg-zinc-800" />
      ) : error ? (
        <span className="flex items-center gap-2 text-lg font-semibold text-zinc-400">
          —
          <button
            onClick={onRetry}
            aria-label={`Retry loading ${label}`}
            className="text-xs text-blue-600 underline"
          >
            retry
          </button>
        </span>
      ) : (
        <span className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">{value}</span>
      )}
    </div>
  );
}

interface KpiRowProps {
  exceptions: AttendanceException[];
  loading: boolean;
  error: boolean;
  onRetry: () => void;
}

// Two genuinely distinct counts, both derivable from data already on the
// page — no backend aggregate needed. "Currently Outside" and "Stale
// Signals" read different fields (needs_attention vs monitoring_status),
// unlike the original 4-card spec's "Exits Today"/"Returns Today" (no
// endpoint returns that) or a naive second "Unresolved Alerts" card (would
// have read the same boolean as "Currently Outside" and always shown an
// identical number — caught during design review).
export default function KpiRow({ exceptions, loading, error, onRetry }: KpiRowProps) {
  const { currentlyOutside, staleSignals } = useMemo(() => computeKpis(exceptions), [exceptions]);

  return (
    <div className="flex gap-3" aria-live="polite">
      <KpiCard
        label="Currently Outside"
        value={currentlyOutside}
        loading={loading}
        error={error}
        onRetry={onRetry}
      />
      <KpiCard
        label="Stale Signals"
        value={staleSignals}
        loading={loading}
        error={error}
        onRetry={onRetry}
      />
    </div>
  );
}
