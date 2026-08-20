"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AxiosError } from "axios";

import AppHeader from "../../components/AppHeader";
import RequireAuth from "../../components/RequireAuth";
import { Employee, listEmployees } from "../../lib/employeeService";
import {
  DeviationFlagList,
  EmployeeBaseline,
  EmployeeDeviationFlag,
  ImpossibleTravelRejectionList,
  InsightList,
  ReviewStatus,
  RunDetectionResult,
  RebuildBaselinesResult,
  SyntheticDataRun,
  generateSyntheticData,
  getBaseline,
  listDeviationFlags,
  listImpossibleTravelRejections,
  listInsights,
  rebuildBaselines,
  reviewFlag,
  runDetection,
} from "../../lib/workforceIntelligenceService";

const PAGE_SIZE = 20;

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function ninetyDaysAgoIso(): string {
  const d = new Date();
  d.setDate(d.getDate() - 90);
  return d.toISOString().slice(0, 10);
}

function severityBadgeClass(severity: string): string {
  return severity === "high"
    ? "rounded bg-red-50 px-2 py-0.5 text-xs text-red-700 dark:bg-red-950 dark:text-red-300"
    : "rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-950 dark:text-amber-300";
}

function formatZ(z: number | null): string {
  return z === null ? "—" : z.toFixed(2);
}

function formatNum(n: number): string {
  return Number.isFinite(n) ? n.toFixed(1) : "—";
}

// Plain-English labels for the metric keys the backend emits (snake_case,
// unit baked into the name) — HR/Admin readers shouldn't have to parse
// "checkin_time_of_day_minutes" themselves.
const METRIC_LABELS: Record<string, string> = {
  work_duration_minutes: "Work duration",
  checkin_time_of_day_minutes: "Check-in time",
  break_duration_minutes: "Break duration",
  break_count: "Number of breaks",
  geofence_exit_count: "Site exits",
};

function metricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? metric.replace(/_/g, " ");
}

// Renders a raw metric value in the unit an HR reader actually thinks in,
// instead of the backend's internal representation (minutes since
// midnight, raw minute counts).
function formatMetricValue(metric: string, value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (metric === "checkin_time_of_day_minutes") {
    const totalMinutes = Math.round(value);
    const hours = Math.floor(totalMinutes / 60) % 24;
    const minutes = totalMinutes % 60;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
  }
  if (metric.endsWith("_duration_minutes")) {
    const totalMinutes = Math.round(value);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`;
  }
  if (metric.endsWith("_count")) {
    return String(Math.round(value));
  }
  return formatNum(value);
}

// Turns the self/peer z-scores into a sentence an HR reader doesn't need
// a stats background to parse — magnitude in words plus direction, or a
// plain "broke a fixed pattern" note when there's no self_z (e.g. a count
// metric that had exactly one value historically).
function deviationSummary(f: EmployeeDeviationFlag): string {
  if (f.self_z === null) {
    return "Broke a pattern that had never varied before";
  }
  const magnitude = Math.abs(f.self_z);
  const direction = f.observed_value >= f.self_mean ? "above" : "below";
  const word = magnitude >= 5 ? "extremely" : magnitude >= 3 ? "highly" : "moderately";
  return `${word} unusual — ${magnitude.toFixed(1)}× ${direction} this person's usual pattern`;
}

function AnomalyDetectionPageContent() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [employeeSearch, setEmployeeSearch] = useState("");
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(null);

  const [flags, setFlags] = useState<DeviationFlagList | null>(null);
  const [flagsLoading, setFlagsLoading] = useState(false);
  const [flagsError, setFlagsError] = useState<string | null>(null);
  const [flagsOffset, setFlagsOffset] = useState(0);

  const [rejections, setRejections] = useState<ImpossibleTravelRejectionList | null>(null);
  const [rejectionsLoading, setRejectionsLoading] = useState(false);
  const [rejectionsError, setRejectionsError] = useState<string | null>(null);
  const [rejectionsOffset, setRejectionsOffset] = useState(0);

  const [activeTab, setActiveTab] = useState<"insights" | "evidence">("insights");
  const [insights, setInsights] = useState<InsightList | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [insightsError, setInsightsError] = useState<string | null>(null);
  const [insightsOffset, setInsightsOffset] = useState(0);
  const [reviewingId, setReviewingId] = useState<string | null>(null);

  const [baseline, setBaseline] = useState<EmployeeBaseline | null>(null);
  const [baselineLoading, setBaselineLoading] = useState(false);
  const [baselineError, setBaselineError] = useState<string | null>(null);

  const [showActions, setShowActions] = useState(false);

  const [genStart, setGenStart] = useState(ninetyDaysAgoIso());
  const [genEnd, setGenEnd] = useState(todayIso());
  const [genSeed, setGenSeed] = useState(1);
  const [genAnomalyConfig, setGenAnomalyConfig] = useState("{}");
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [genResult, setGenResult] = useState<SyntheticDataRun | null>(null);

  const [rebuildStart, setRebuildStart] = useState(ninetyDaysAgoIso());
  const [rebuildEnd, setRebuildEnd] = useState(todayIso());
  const [rebuilding, setRebuilding] = useState(false);
  const [rebuildError, setRebuildError] = useState<string | null>(null);
  const [rebuildResult, setRebuildResult] = useState<RebuildBaselinesResult | null>(null);

  const [detectStart, setDetectStart] = useState(ninetyDaysAgoIso());
  const [detectEnd, setDetectEnd] = useState(todayIso());
  const [detecting, setDetecting] = useState(false);
  const [detectError, setDetectError] = useState<string | null>(null);
  const [detectResult, setDetectResult] = useState<RunDetectionResult | null>(null);

  useEffect(() => {
    listEmployees()
      .then(setEmployees)
      .catch((err) => setLoadError(apiErrorMessage(err)));
  }, []);

  const searchParams = useSearchParams();
  useEffect(() => {
    // Notification "View details" deep link (?employee_id=...) — a
    // page-level link, not a specific flag id, since detection reruns
    // delete and recreate flag rows for a window (see
    // WorkforceIntelligenceService.run_detection) and a flag id from an
    // email sent days ago may no longer exist by the time it's clicked.
    const employeeIdParam = searchParams.get("employee_id");
    if (employeeIdParam) {
      setSelectedEmployeeId(employeeIdParam);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const employeeName = useMemo(() => {
    const byId = new Map(employees.map((e) => [e.id, `${e.user.full_name} (${e.employee_code})`]));
    return (id: string) => byId.get(id) ?? id;
  }, [employees]);

  const filteredEmployees = useMemo(() => {
    const q = employeeSearch.trim().toLowerCase();
    if (!q) return [];
    return employees
      .filter(
        (e) =>
          e.user.full_name.toLowerCase().includes(q) ||
          e.employee_code.toLowerCase().includes(q),
      )
      .slice(0, 10);
  }, [employees, employeeSearch]);

  const loadFlags = useCallback(
    (offset: number) => {
      setFlagsLoading(true);
      setFlagsError(null);
      listDeviationFlags({
        employee_id: selectedEmployeeId ?? undefined,
        limit: PAGE_SIZE,
        offset,
      })
        .then((result) => {
          setFlags(result);
          setFlagsOffset(offset);
        })
        .catch((err) => setFlagsError(apiErrorMessage(err)))
        .finally(() => setFlagsLoading(false));
    },
    [selectedEmployeeId],
  );

  const loadRejections = useCallback(
    (offset: number) => {
      setRejectionsLoading(true);
      setRejectionsError(null);
      listImpossibleTravelRejections({
        employee_id: selectedEmployeeId ?? undefined,
        limit: PAGE_SIZE,
        offset,
      })
        .then((result) => {
          setRejections(result);
          setRejectionsOffset(offset);
        })
        .catch((err) => setRejectionsError(apiErrorMessage(err)))
        .finally(() => setRejectionsLoading(false));
    },
    [selectedEmployeeId],
  );

  const loadInsights = useCallback(
    (offset: number) => {
      setInsightsLoading(true);
      setInsightsError(null);
      listInsights({
        employee_id: selectedEmployeeId ?? undefined,
        limit: PAGE_SIZE,
        offset,
      })
        .then((result) => {
          setInsights(result);
          setInsightsOffset(offset);
        })
        .catch((err) => setInsightsError(apiErrorMessage(err)))
        .finally(() => setInsightsLoading(false));
    },
    [selectedEmployeeId],
  );

  async function submitReview(flagId: string, status: ReviewStatus) {
    setReviewingId(flagId);
    try {
      await reviewFlag(flagId, status);
      loadInsights(insightsOffset);
    } catch (err) {
      setInsightsError(apiErrorMessage(err));
    } finally {
      setReviewingId(null);
    }
  }

  const loadBaseline = useCallback(() => {
    if (!selectedEmployeeId) {
      setBaseline(null);
      return;
    }
    setBaselineLoading(true);
    setBaselineError(null);
    getBaseline(selectedEmployeeId)
      .then(setBaseline)
      .catch((err) => setBaselineError(apiErrorMessage(err)))
      .finally(() => setBaselineLoading(false));
  }, [selectedEmployeeId]);

  useEffect(() => {
    loadInsights(0);
    loadFlags(0);
    loadRejections(0);
    loadBaseline();
    // Selecting/clearing an employee re-scopes every section back to page 1.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedEmployeeId]);

  function selectEmployee(id: string) {
    setSelectedEmployeeId(id);
    setEmployeeSearch("");
    setGenResult(null);
    setRebuildResult(null);
    setDetectResult(null);
    setGenError(null);
    setRebuildError(null);
    setDetectError(null);
  }

  function clearSelection() {
    setSelectedEmployeeId(null);
  }

  async function submitGenerate() {
    if (!selectedEmployeeId) return;
    let anomalyConfig: Record<string, unknown>;
    try {
      anomalyConfig = genAnomalyConfig.trim() ? JSON.parse(genAnomalyConfig) : {};
    } catch {
      setGenError("anomaly_config must be valid JSON");
      return;
    }
    setGenerating(true);
    setGenError(null);
    setGenResult(null);
    try {
      const run = await generateSyntheticData({
        employee_ids: [selectedEmployeeId],
        date_range_start: genStart,
        date_range_end: genEnd,
        anomaly_config: anomalyConfig,
        seed: genSeed,
      });
      setGenResult(run);
    } catch (err) {
      setGenError(apiErrorMessage(err));
    } finally {
      setGenerating(false);
    }
  }

  async function submitRebuild() {
    if (!selectedEmployeeId) return;
    setRebuilding(true);
    setRebuildError(null);
    setRebuildResult(null);
    try {
      const result = await rebuildBaselines({
        employee_ids: [selectedEmployeeId],
        window_start: rebuildStart,
        window_end: rebuildEnd,
      });
      setRebuildResult(result);
      loadBaseline();
    } catch (err) {
      setRebuildError(apiErrorMessage(err));
    } finally {
      setRebuilding(false);
    }
  }

  async function submitDetect() {
    if (!selectedEmployeeId) return;
    setDetecting(true);
    setDetectError(null);
    setDetectResult(null);
    try {
      const result = await runDetection({
        employee_ids: [selectedEmployeeId],
        window_start: detectStart,
        window_end: detectEnd,
      });
      setDetectResult(result);
      loadFlags(0);
    } catch (err) {
      setDetectError(apiErrorMessage(err));
    } finally {
      setDetecting(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader current="anomaly-detection" title="Anomaly Detection" />

      <div className="mx-6 mt-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-200">
        Deviation flags are statistical outliers against an employee&apos;s own history, not
        verdicts — always confirm before acting. Internal analytics, HR/Admin/SuperAdmin only.
      </div>

      {loadError && (
        <p className="mx-6 mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {loadError}
        </p>
      )}

      <div className="flex flex-col gap-6 p-6">
        {/* Employee scope */}
        <div className="flex items-center gap-3">
          {selectedEmployeeId ? (
            <div className="flex items-center gap-2 rounded-lg border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800">
              <span className="font-medium text-zinc-900 dark:text-zinc-50">
                {employeeName(selectedEmployeeId)}
              </span>
              <button onClick={clearSelection} className="text-xs text-blue-600 underline">
                Clear (view workforce-wide)
              </button>
            </div>
          ) : (
            <div className="relative w-full max-w-md">
              <input
                placeholder="Search employee by name or code to scope this view…"
                value={employeeSearch}
                onChange={(e) => setEmployeeSearch(e.target.value)}
                className="w-full rounded border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              />
              {filteredEmployees.length > 0 && (
                <ul className="absolute z-10 mt-1 w-full rounded border border-zinc-200 bg-white shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
                  {filteredEmployees.map((e) => (
                    <li key={e.id}>
                      <button
                        onClick={() => selectEmployee(e.id)}
                        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-zinc-50 dark:hover:bg-zinc-800"
                      >
                        <span>{e.user.full_name}</span>
                        <span className="text-xs text-zinc-500">{e.employee_code}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800">
          <button
            onClick={() => setActiveTab("insights")}
            className={`px-3 py-2 text-sm font-medium ${
              activeTab === "insights"
                ? "border-b-2 border-zinc-900 text-zinc-900 dark:border-zinc-50 dark:text-zinc-50"
                : "text-zinc-500"
            }`}
          >
            Insights
          </button>
          <button
            onClick={() => setActiveTab("evidence")}
            className={`px-3 py-2 text-sm font-medium ${
              activeTab === "evidence"
                ? "border-b-2 border-zinc-900 text-zinc-900 dark:border-zinc-50 dark:text-zinc-50"
                : "text-zinc-500"
            }`}
          >
            Evidence
          </button>
        </div>

        {/* Insights tab — HIGH-severity flags only, turned into plain-English
            sentences (Module 4). MODERATE flags stay in the Evidence tab's
            raw table, not promoted here (evidence-threshold decision). */}
        {activeTab === "insights" && (
          <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
            <div className="flex items-center justify-between px-4 py-3">
              <h3 className="text-sm font-medium text-zinc-500">
                {selectedEmployeeId ? "Insights for this employee" : "Recent insights (workforce-wide)"}
              </h3>
              <button onClick={() => loadInsights(insightsOffset)} className="text-xs text-blue-600 underline">
                Refresh
              </button>
            </div>
            {insightsError && (
              <p className="mx-4 mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
                {insightsError}
              </p>
            )}
            <div className="flex flex-col gap-3 p-4">
              {insightsLoading && <p className="text-sm text-zinc-500">Loading…</p>}
              {!insightsLoading && insights?.items.length === 0 && (
                <p className="text-sm text-zinc-500">No high-confidence insights — all clear.</p>
              )}
              {!insightsLoading &&
                insights?.items.map((i) => (
                  <div
                    key={i.id}
                    className="flex flex-col gap-3 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium text-zinc-900 dark:text-zinc-50">
                        {!selectedEmployeeId && `${employeeName(i.employee_id)} — `}
                        {i.title}
                      </span>
                      <div className="flex items-center gap-2">
                        {i.is_synthetic && (
                          <span className="rounded bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                            synthetic
                          </span>
                        )}
                        <span className={severityBadgeClass(i.severity)}>{i.severity}</span>
                      </div>
                    </div>

                    {/* WHAT happened */}
                    <p className="text-sm text-zinc-700 dark:text-zinc-300">{i.summary}</p>

                    {/* WHY it was flagged */}
                    <div className="text-sm">
                      <span className="font-medium text-zinc-500">Why was this detected? </span>
                      <span className="text-zinc-600 dark:text-zinc-400">{i.explanation}</span>
                    </div>

                    {/* WHAT the evidence is — human units only, no z-scores */}
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 rounded border border-zinc-100 bg-zinc-50 p-3 text-xs dark:border-zinc-900 dark:bg-zinc-950 sm:grid-cols-3">
                      <div>
                        <dt className="text-zinc-400">Current value</dt>
                        <dd className="text-zinc-800 dark:text-zinc-200">{i.evidence.current}</dd>
                      </div>
                      <div>
                        <dt className="text-zinc-400">Baseline</dt>
                        <dd className="text-zinc-800 dark:text-zinc-200">{i.evidence.baseline}</dd>
                      </div>
                      <div>
                        <dt className="text-zinc-400">Difference</dt>
                        <dd className="text-zinc-800 dark:text-zinc-200">{i.evidence.difference}</dd>
                      </div>
                      <div>
                        <dt className="text-zinc-400">Historical observations</dt>
                        <dd className="text-zinc-800 dark:text-zinc-200">
                          {i.evidence.historical_observations ?? "—"}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-zinc-400">Severity</dt>
                        <dd className="text-zinc-800 dark:text-zinc-200">{i.evidence.severity}</dd>
                      </div>
                      <div>
                        <dt className="text-zinc-400">Detection type</dt>
                        <dd className="text-zinc-800 dark:text-zinc-200">
                          {i.evidence.detection_type}
                        </dd>
                      </div>
                    </dl>

                    <details className="text-xs text-zinc-500">
                      <summary className="cursor-pointer select-none">Technical Details</summary>
                      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono sm:grid-cols-3">
                        <div>
                          <dt className="text-zinc-400">metric</dt>
                          <dd>{i.technical.metric}</dd>
                        </div>
                        <div>
                          <dt className="text-zinc-400">self_z</dt>
                          <dd>{formatZ(i.technical.self_z)}</dd>
                        </div>
                        <div>
                          <dt className="text-zinc-400">peer_z</dt>
                          <dd>{formatZ(i.technical.peer_z)}</dd>
                        </div>
                        <div>
                          <dt className="text-zinc-400">self_n</dt>
                          <dd>{i.technical.self_n ?? "—"}</dd>
                        </div>
                        <div>
                          <dt className="text-zinc-400">peer_n</dt>
                          <dd>{i.technical.peer_n ?? "—"}</dd>
                        </div>
                      </dl>
                    </details>

                    {/* WHAT the HR/Admin user can do next */}
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-zinc-400">
                        {i.review_status === "new"
                          ? "Not yet reviewed"
                          : `${i.review_status} ${i.reviewed_at ? `on ${new Date(i.reviewed_at).toLocaleDateString()}` : ""}`}
                      </span>
                      <div className="flex gap-2 text-xs">
                        {!selectedEmployeeId && (
                          <button
                            onClick={() => selectEmployee(i.employee_id)}
                            className="text-blue-600 underline"
                          >
                            View Employee
                          </button>
                        )}
                        {i.review_status !== "reviewed" && (
                          <button
                            disabled={reviewingId === i.id}
                            onClick={() => submitReview(i.id, "reviewed")}
                            className="text-blue-600 underline disabled:opacity-30"
                          >
                            Mark as Reviewed
                          </button>
                        )}
                        {i.review_status !== "dismissed" && (
                          <button
                            disabled={reviewingId === i.id}
                            onClick={() => submitReview(i.id, "dismissed")}
                            className="text-blue-600 underline disabled:opacity-30"
                          >
                            Dismiss
                          </button>
                        )}
                        {i.review_status !== "new" && (
                          <button
                            disabled={reviewingId === i.id}
                            onClick={() => submitReview(i.id, "new")}
                            className="text-blue-600 underline disabled:opacity-30"
                          >
                            Reopen
                          </button>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
            </div>
            {insights && insights.total > PAGE_SIZE && (
              <div className="flex items-center justify-between px-4 py-3 text-xs text-zinc-500">
                <span>
                  {insightsOffset + 1}–{Math.min(insightsOffset + PAGE_SIZE, insights.total)} of{" "}
                  {insights.total}
                </span>
                <div className="flex gap-2">
                  <button
                    disabled={insightsOffset === 0}
                    onClick={() => loadInsights(Math.max(0, insightsOffset - PAGE_SIZE))}
                    className="underline disabled:opacity-30"
                  >
                    Previous
                  </button>
                  <button
                    disabled={insightsOffset + PAGE_SIZE >= insights.total}
                    onClick={() => loadInsights(insightsOffset + PAGE_SIZE)}
                    className="underline disabled:opacity-30"
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === "evidence" && (
          <>
        {/* Baseline card — only when an employee is selected */}
        {selectedEmployeeId && (
          <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <h3 className="mb-3 text-sm font-medium text-zinc-500">Baseline</h3>
            {baselineLoading && <p className="text-sm text-zinc-500">Loading…</p>}
            {baselineError && (
              <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
                {baselineError}
              </p>
            )}
            {!baselineLoading && !baselineError && baseline === null && (
              <p className="text-sm text-zinc-500">
                No baseline yet for this employee — use Rebuild baseline below (needs at least
                40 clean workdays of history in the chosen window).
              </p>
            )}
            {!baselineLoading && !baselineError && baseline !== null && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[700px] text-left text-sm">
                  <thead className="text-xs uppercase text-zinc-500">
                    <tr>
                      <th className="py-1 pr-4">Metric</th>
                      <th className="py-1 pr-4">This employee&apos;s normal</th>
                      <th className="py-1 pr-4">Peer group&apos;s normal</th>
                      <th className="py-1 pr-4">Compared against</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(baseline.metric_stats).map(([metric, stats]) => (
                      <tr key={metric} className="border-t border-zinc-100 dark:border-zinc-900">
                        <td className="py-1.5 pr-4 text-zinc-900 dark:text-zinc-50">
                          {metricLabel(metric)}
                        </td>
                        <td className="py-1.5 pr-4 text-zinc-600 dark:text-zinc-400">
                          {stats.self.mean !== null
                            ? `usually ${formatMetricValue(metric, stats.self.mean)} (±${formatMetricValue(metric, stats.self.std ?? 0)}, from ${stats.self.n} days)`
                            : "—"}
                        </td>
                        <td className="py-1.5 pr-4 text-zinc-600 dark:text-zinc-400">
                          {stats.peer.mean !== null
                            ? `usually ${formatMetricValue(metric, stats.peer.mean)} (±${formatMetricValue(metric, stats.peer.std ?? 0)}, from ${stats.peer.n} days)`
                            : "—"}
                        </td>
                        <td className="py-1.5 pr-4 text-zinc-600 dark:text-zinc-400">
                          {stats.peer.source === "department" ? "Department" : "Company-wide"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-zinc-400">
                  This employee&apos;s normal pattern, calculated from {baseline.window_start} to{" "}
                  {baseline.window_end} (last recalculated{" "}
                  {new Date(baseline.computed_at).toLocaleString()}). Deviation flags below compare
                  new readings against these numbers.
                </p>
              </div>
            )}
          </div>
        )}

        {/* Deviation flags */}
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center justify-between px-4 py-3">
            <h3 className="text-sm font-medium text-zinc-500">
              {selectedEmployeeId ? "Deviation flags for this employee" : "Recent deviation flags (workforce-wide)"}
            </h3>
            <button onClick={() => loadFlags(flagsOffset)} className="text-xs text-blue-600 underline">
              Refresh
            </button>
          </div>
          {flagsError && (
            <p className="mx-4 mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              {flagsError}
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] text-left text-sm">
              <thead className="border-y border-zinc-200 bg-zinc-50 text-xs uppercase text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                <tr>
                  {!selectedEmployeeId && <th className="px-4 py-2">Employee</th>}
                  <th className="px-4 py-2">Metric</th>
                  <th className="px-4 py-2">Observed</th>
                  <th className="px-4 py-2">What this means</th>
                  <th
                    className="px-4 py-2"
                    title="Self z: how many standard deviations this reading is from the employee's own historical average. Peer z: the same, compared against their department/company peers. 0 = typical, further from 0 = more unusual."
                  >
                    Self z / Peer z
                  </th>
                  <th className="px-4 py-2">Severity</th>
                  <th className="px-4 py-2">Occurred</th>
                  <th className="px-4 py-2">Data source</th>
                </tr>
              </thead>
              <tbody>
                {flagsLoading && (
                  <tr>
                    <td colSpan={8} className="px-4 py-6 text-center text-zinc-500">
                      Loading…
                    </td>
                  </tr>
                )}
                {!flagsLoading && flags?.items.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-6 text-center text-zinc-500">
                      No deviation flags — all clear.
                    </td>
                  </tr>
                )}
                {!flagsLoading &&
                  flags?.items.map((f) => (
                    <tr key={f.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                      {!selectedEmployeeId && (
                        <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">
                          {employeeName(f.employee_id)}
                        </td>
                      )}
                      <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">
                        {metricLabel(f.metric)}
                      </td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                        {formatMetricValue(f.metric, f.observed_value)}
                      </td>
                      <td className="max-w-[280px] px-4 py-2 text-zinc-700 dark:text-zinc-300">
                        {deviationSummary(f)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-zinc-500 dark:text-zinc-500">
                        {formatZ(f.self_z)} / {formatZ(f.peer_z)}
                      </td>
                      <td className="px-4 py-2">
                        <span className={severityBadgeClass(f.severity)}>{f.severity}</span>
                      </td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                        {new Date(f.occurred_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2">
                        <span className="rounded bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
                          {f.is_synthetic ? "Synthetic" : "Live"}
                        </span>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {flags && flags.items.length > 0 && (
            <p className="px-4 pb-3 text-xs text-zinc-400">
              &quot;Self z / Peer z&quot; is the raw statistical measure behind the plain-English
              summary — 0 is typical, the further from 0 the more unusual. Kept here for audit
              purposes.
            </p>
          )}
          {flags && flags.total > PAGE_SIZE && (
            <div className="flex items-center justify-between px-4 py-3 text-xs text-zinc-500">
              <span>
                {flagsOffset + 1}–{Math.min(flagsOffset + PAGE_SIZE, flags.total)} of {flags.total}
              </span>
              <div className="flex gap-2">
                <button
                  disabled={flagsOffset === 0}
                  onClick={() => loadFlags(Math.max(0, flagsOffset - PAGE_SIZE))}
                  className="underline disabled:opacity-30"
                >
                  Previous
                </button>
                <button
                  disabled={flagsOffset + PAGE_SIZE >= flags.total}
                  onClick={() => loadFlags(flagsOffset + PAGE_SIZE)}
                  className="underline disabled:opacity-30"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Impossible-travel rejections — always workforce-wide-capable audit log */}
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center justify-between px-4 py-3">
            <h3 className="text-sm font-medium text-zinc-500">
              {selectedEmployeeId
                ? "Impossible-travel check-in rejections for this employee"
                : "Impossible-travel check-in rejections (workforce-wide)"}
            </h3>
            <button onClick={() => loadRejections(rejectionsOffset)} className="text-xs text-blue-600 underline">
              Refresh
            </button>
          </div>
          {rejectionsError && (
            <p className="mx-4 mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
              {rejectionsError}
            </p>
          )}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-y border-zinc-200 bg-zinc-50 text-xs uppercase text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                <tr>
                  {!selectedEmployeeId && <th className="px-4 py-2">Employee</th>}
                  <th className="px-4 py-2">Attempted</th>
                  <th className="px-4 py-2">Distance</th>
                  <th className="px-4 py-2">Elapsed</th>
                  <th className="px-4 py-2">Implied speed</th>
                  <th className="px-4 py-2">Risk</th>
                </tr>
              </thead>
              <tbody>
                {rejectionsLoading && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-zinc-500">
                      Loading…
                    </td>
                  </tr>
                )}
                {!rejectionsLoading && rejections?.items.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-6 text-center text-zinc-500">
                      No rejections recorded.
                    </td>
                  </tr>
                )}
                {!rejectionsLoading &&
                  rejections?.items.map((r) => (
                    <tr key={r.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                      {!selectedEmployeeId && (
                        <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">
                          {employeeName(r.employee_id)}
                        </td>
                      )}
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                        {new Date(r.attempted_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                        {formatNum(r.distance_km)} km
                      </td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                        {formatNum(r.elapsed_hours)} h
                      </td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                        {formatNum(r.implied_speed_kmh)} km/h
                      </td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                        {r.risk_score.toFixed(2)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
          {rejections && rejections.total > PAGE_SIZE && (
            <div className="flex items-center justify-between px-4 py-3 text-xs text-zinc-500">
              <span>
                {rejectionsOffset + 1}–{Math.min(rejectionsOffset + PAGE_SIZE, rejections.total)} of{" "}
                {rejections.total}
              </span>
              <div className="flex gap-2">
                <button
                  disabled={rejectionsOffset === 0}
                  onClick={() => loadRejections(Math.max(0, rejectionsOffset - PAGE_SIZE))}
                  className="underline disabled:opacity-30"
                >
                  Previous
                </button>
                <button
                  disabled={rejectionsOffset + PAGE_SIZE >= rejections.total}
                  onClick={() => loadRejections(rejectionsOffset + PAGE_SIZE)}
                  className="underline disabled:opacity-30"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Actions — scoped to the selected employee only */}
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800">
          <button
            onClick={() => setShowActions((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-3 text-left"
          >
            <h3 className="text-sm font-medium text-zinc-500">Admin actions</h3>
            <span className="text-xs text-blue-600 underline">{showActions ? "Hide" : "Show"}</span>
          </button>
          {showActions && (
            <div className="flex flex-col gap-6 border-t border-zinc-200 p-4 dark:border-zinc-800">
              {!selectedEmployeeId && (
                <p className="text-sm text-zinc-500">
                  Select an employee above to enable these actions — each one operates on a
                  single employee at a time.
                </p>
              )}

              {/* Generate synthetic data */}
              <div className="flex flex-col gap-2">
                <h4 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                  Generate synthetic data
                </h4>
                <div className="flex flex-wrap items-end gap-3">
                  <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                    Start
                    <input
                      type="date"
                      value={genStart}
                      onChange={(e) => setGenStart(e.target.value)}
                      className="rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                    End
                    <input
                      type="date"
                      value={genEnd}
                      onChange={(e) => setGenEnd(e.target.value)}
                      className="rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                    Seed
                    <input
                      type="number"
                      value={genSeed}
                      onChange={(e) => setGenSeed(Number(e.target.value))}
                      className="w-24 rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                  <label className="flex flex-1 min-w-[240px] flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                    anomaly_config (JSON)
                    <input
                      type="text"
                      value={genAnomalyConfig}
                      onChange={(e) => setGenAnomalyConfig(e.target.value)}
                      placeholder='{"late_arrival": 0.2}'
                      className="rounded border border-zinc-300 px-2 py-1.5 font-mono text-xs dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                  <button
                    onClick={submitGenerate}
                    disabled={!selectedEmployeeId || generating}
                    className="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
                  >
                    {generating ? "Generating…" : "Generate"}
                  </button>
                </div>
                {genError && <p className="text-xs text-red-600">{genError}</p>}
                {genResult && (
                  <p className="text-xs text-zinc-500">
                    Run {genResult.id} — status {genResult.status}
                    {genResult.row_counts && ` — ${JSON.stringify(genResult.row_counts)}`}
                  </p>
                )}
              </div>

              {/* Rebuild baseline */}
              <div className="flex flex-col gap-2">
                <h4 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                  Rebuild baseline
                </h4>
                <div className="flex flex-wrap items-end gap-3">
                  <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                    Window start
                    <input
                      type="date"
                      value={rebuildStart}
                      onChange={(e) => setRebuildStart(e.target.value)}
                      className="rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                    Window end
                    <input
                      type="date"
                      value={rebuildEnd}
                      onChange={(e) => setRebuildEnd(e.target.value)}
                      className="rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                  <button
                    onClick={submitRebuild}
                    disabled={!selectedEmployeeId || rebuilding}
                    className="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
                  >
                    {rebuilding ? "Rebuilding…" : "Rebuild"}
                  </button>
                </div>
                {rebuildError && <p className="text-xs text-red-600">{rebuildError}</p>}
                {rebuildResult && (
                  <p className="text-xs text-zinc-500">
                    {rebuildResult.built.length > 0
                      ? "Baseline rebuilt."
                      : rebuildResult.skipped_insufficient_history.length > 0
                        ? "Skipped — insufficient history in this window."
                        : "Skipped — employee is terminated."}
                  </p>
                )}
              </div>

              {/* Run detection */}
              <div className="flex flex-col gap-2">
                <h4 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
                  Run detection
                </h4>
                <div className="flex flex-wrap items-end gap-3">
                  <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                    Window start
                    <input
                      type="date"
                      value={detectStart}
                      onChange={(e) => setDetectStart(e.target.value)}
                      className="rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                  <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                    Window end
                    <input
                      type="date"
                      value={detectEnd}
                      onChange={(e) => setDetectEnd(e.target.value)}
                      className="rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
                    />
                  </label>
                  <button
                    onClick={submitDetect}
                    disabled={!selectedEmployeeId || detecting}
                    className="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
                  >
                    {detecting ? "Running…" : "Run detection"}
                  </button>
                </div>
                {detectError && <p className="text-xs text-red-600">{detectError}</p>}
                {detectResult && (
                  <p className="text-xs text-zinc-500">
                    {detectResult.skipped_no_baseline.length > 0
                      ? "Skipped — no baseline yet for this employee, rebuild one first."
                      : `${Object.values(detectResult.flag_counts).reduce((a, b) => a + b, 0)} flag(s) produced.`}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function AnomalyDetectionPage() {
  return (
    <RequireAuth allowedRoles={["hr_manager", "admin", "super_admin"]}>
      <Suspense fallback={null}>
        <AnomalyDetectionPageContent />
      </Suspense>
    </RequireAuth>
  );
}
