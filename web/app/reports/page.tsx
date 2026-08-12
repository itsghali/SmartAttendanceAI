"use client";

import { useCallback, useEffect, useState } from "react";
import { AxiosError } from "axios";

import AppHeader from "../../components/AppHeader";
import RequireAuth from "../../components/RequireAuth";
import {
  ProblemReport,
  ProblemReportStatus,
  listProblemReports,
  resolveProblemReport,
} from "../../lib/problemReportService";

type FilterTab = ProblemReportStatus | "all";

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
}

function ReportsPageContent() {
  const [tab, setTab] = useState<FilterTab>("open");
  const [reports, setReports] = useState<ProblemReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [resolveError, setResolveError] = useState<string | null>(null);

  const load = useCallback(async (nextTab: FilterTab) => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await listProblemReports({
        status: nextTab === "all" ? undefined : nextTab,
        limit: 200,
      });
      setReports(data.items);
    } catch (err) {
      setLoadError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => load(tab), 0);
    return () => clearTimeout(timer);
  }, [tab, load]);

  async function handleResolve(report: ProblemReport) {
    setResolvingId(report.id);
    setResolveError(null);
    try {
      await resolveProblemReport(report.id);
      // Resolved reports drop out of the "open" tab immediately rather than
      // waiting for the next poll/reload — otherwise the row HR just acted
      // on sits there looking unresolved.
      setReports((prev) =>
        tab === "open" ? prev.filter((r) => r.id !== report.id) : prev,
      );
    } catch (err) {
      setResolveError(`${report.employee_full_name}: ${apiErrorMessage(err)}`);
    } finally {
      setResolvingId(null);
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader current="reports" title="Problem Reports" />

      <div className="flex flex-col gap-4 p-6">
        <div className="flex items-center gap-2">
          {(["open", "resolved", "all"] as FilterTab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={
                "rounded px-3 py-1.5 text-sm capitalize " +
                (tab === t
                  ? "bg-zinc-900 text-white dark:bg-zinc-50 dark:text-zinc-900"
                  : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400")
              }
            >
              {t}
            </button>
          ))}
        </div>

        {loadError && (
          <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            {loadError}
          </p>
        )}
        {resolveError && (
          <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            {resolveError}
          </p>
        )}
        {loading && <p className="text-sm text-zinc-500">Loading…</p>}

        {!loading && (
          <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
            <table className="w-full min-w-[900px] text-left text-sm">
              <thead className="border-b border-zinc-200 bg-zinc-50 text-xs uppercase text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                <tr>
                  <th className="px-4 py-2">Employee</th>
                  <th className="px-4 py-2">Reported</th>
                  <th className="px-4 py-2">Message</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {reports.map((r) => (
                  <tr key={r.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                    <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">
                      {r.employee_full_name}
                      <div className="font-mono text-xs text-zinc-500">{r.employee_code}</div>
                    </td>
                    <td className="px-4 py-2 whitespace-nowrap text-zinc-600 dark:text-zinc-400">
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 max-w-[420px] text-zinc-600 dark:text-zinc-400">
                      {r.message}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={
                          r.status === "open"
                            ? "rounded bg-red-50 px-2 py-0.5 text-xs text-red-700 dark:bg-red-950 dark:text-red-300"
                            : "rounded bg-green-50 px-2 py-0.5 text-xs text-green-700 dark:bg-green-950 dark:text-green-300"
                        }
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      {r.status === "open" && (
                        <button
                          onClick={() => handleResolve(r)}
                          disabled={resolvingId === r.id}
                          className="text-xs text-blue-600 underline disabled:opacity-50"
                        >
                          {resolvingId === r.id ? "Resolving…" : "Mark resolved"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
                {reports.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-zinc-500">
                      No {tab === "all" ? "" : tab} problem reports.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ReportsPage() {
  return (
    <RequireAuth allowedRoles={["hr_manager", "admin", "super_admin"]}>
      <ReportsPageContent />
    </RequireAuth>
  );
}
