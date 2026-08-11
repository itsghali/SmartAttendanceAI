"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AxiosError } from "axios";

import RequireAuth from "../../components/RequireAuth";
import { useAuth } from "../../lib/auth-context";
import { Employee, listEmployees } from "../../lib/employeeService";
import {
  AttendanceException,
  FaceVerificationAttempt,
  GeofenceEventSummary,
  listAttendanceExceptions,
  getEmployeeFaceAttempts,
  getEmployeeGeofenceHistory,
} from "../../lib/siteStatusService";

// Polling interval for the exceptions list (design doc's "The Assignment" —
// picked here rather than left implicit). Short enough for same-day triage,
// long enough not to hammer the API for a screen that isn't push-driven.
const POLL_INTERVAL_MS = 30_000;
const HISTORY_PAGE_SIZE = 50;

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
}

function statusLabel(status: AttendanceException["monitoring_status"]): string {
  switch (status) {
    case "not_monitored":
      return "Not monitored";
    case "on_break":
      return "On break";
    case "stale":
      return "Stale";
    case "live":
      return "Live";
    default:
      return "Unknown";
  }
}

function statusBadgeClass(status: AttendanceException["monitoring_status"]): string {
  switch (status) {
    case "not_monitored":
      return "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
    case "stale":
      return "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300";
    case "on_break":
      return "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300";
    case "live":
      return "bg-green-100 text-green-800 dark:bg-green-950 dark:text-green-300";
    default:
      return "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
  }
}

function ExceptionRow({
  row,
  onOpenHistory,
}: {
  row: AttendanceException;
  onOpenHistory: (employeeId: string, name: string) => void;
}) {
  return (
    <button
      onClick={() => onOpenHistory(row.employee_id, row.employee_full_name)}
      className="flex w-full items-center justify-between rounded border border-zinc-200 px-3 py-2 text-left text-sm hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-900"
    >
      <span className="flex flex-col">
        <span className="font-medium text-zinc-900 dark:text-zinc-50">
          {row.employee_full_name}
        </span>
        <span className="text-xs text-zinc-500">{row.employee_code}</span>
      </span>
      <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusBadgeClass(row.monitoring_status)}`}>
        {statusLabel(row.monitoring_status)}
      </span>
    </button>
  );
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  enter: "Entered",
  exit: "Exited",
  return: "Returned",
  check_in: "Checked in",
  check_out: "Checked out",
};

const FAILURE_REASON_LABELS: Record<string, string> = {
  no_face: "No face detected",
  multiple_faces: "Multiple faces detected",
  invalid_image: "Invalid image",
  not_enrolled: "Not enrolled",
  low_similarity: "Face did not match enrolled profile",
  liveness_failed: "Liveness check failed",
  model_unavailable: "Face model unavailable",
  profile_corrupted: "Enrolled profile corrupted",
};

function FaceAttemptsSection({
  employeeId,
  dateFrom,
  dateTo,
}: {
  employeeId: string;
  dateFrom: string;
  dateTo: string;
}) {
  const [items, setItems] = useState<FaceVerificationAttempt[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (nextOffset: number) => {
      setLoading(true);
      setLoadError(null);
      try {
        const attempts = await getEmployeeFaceAttempts(employeeId, {
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          limit: HISTORY_PAGE_SIZE,
          offset: nextOffset,
        });
        setItems(attempts.items);
        setTotal(attempts.total);
        setOffset(nextOffset);
      } catch (err) {
        setLoadError(apiErrorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [employeeId, dateFrom, dateTo],
  );

  useEffect(() => {
    // Same react-hooks/set-state-in-effect fix as HistoryPanel — see its comment.
    const timer = setTimeout(() => load(0), 0);
    return () => clearTimeout(timer);
  }, [load]);

  const hasNextPage = offset + items.length < total;
  const hasPrevPage = offset > 0;

  return (
    <div className="flex flex-col gap-2 border-t border-zinc-200 pt-3 dark:border-zinc-800">
      <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
        Face verification attempts
      </h3>

      {loadError && <p className="text-sm text-red-600">{loadError}</p>}
      {loading && <p className="text-sm text-zinc-400">Loading…</p>}
      {!loading && items.length === 0 && !loadError && (
        <p className="text-sm text-zinc-400">No face verification attempts for this range.</p>
      )}

      <ul className="flex flex-col gap-1">
        {items.map((attempt) => (
          <li
            key={attempt.id}
            className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1.5 text-sm dark:border-zinc-800"
          >
            <span className="flex flex-col">
              <span
                className={`font-medium ${
                  attempt.passed
                    ? "text-green-700 dark:text-green-400"
                    : "text-red-700 dark:text-red-400"
                }`}
              >
                {attempt.passed ? "Matched" : "Rejected"}
              </span>
              {attempt.failure_reason && (
                <span className="text-xs text-zinc-500">
                  {FAILURE_REASON_LABELS[attempt.failure_reason] ?? attempt.failure_reason}
                </span>
              )}
            </span>
            <span className="text-xs text-zinc-500">
              {new Date(attempt.created_at).toLocaleString()}
            </span>
          </li>
        ))}
      </ul>

      {total > HISTORY_PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <button
            onClick={() => load(Math.max(0, offset - HISTORY_PAGE_SIZE))}
            disabled={!hasPrevPage || loading}
            className="text-blue-600 underline disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-xs text-zinc-500">
            {offset + 1}–{Math.min(offset + items.length, total)} of {total}
          </span>
          <button
            onClick={() => load(offset + HISTORY_PAGE_SIZE)}
            disabled={!hasNextPage || loading}
            className="text-blue-600 underline disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function HistoryPanel({
  employeeId,
  employeeName,
  onClose,
}: {
  employeeId: string;
  employeeName: string;
  onClose: () => void;
}) {
  const [items, setItems] = useState<GeofenceEventSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (nextOffset: number) => {
      setLoading(true);
      setLoadError(null);
      try {
        const history = await getEmployeeGeofenceHistory(employeeId, {
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          limit: HISTORY_PAGE_SIZE,
          offset: nextOffset,
        });
        setItems(history.items);
        setTotal(history.total);
        setOffset(nextOffset);
      } catch (err) {
        setLoadError(apiErrorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [employeeId, dateFrom, dateTo],
  );

  useEffect(() => {
    // A direct `load(0)` call here is a bare synchronous setState-triggering
    // call at the effect's top level, which react-hooks/set-state-in-effect
    // flags — deferring through setTimeout makes it a callback reference
    // instead (the rule's own recommended shape), not a behavior change.
    const timer = setTimeout(() => load(0), 0);
    return () => clearTimeout(timer);
  }, [load]);

  const hasNextPage = offset + items.length < total;
  const hasPrevPage = offset > 0;

  return (
    <div className="flex w-[380px] flex-col gap-3 overflow-y-auto border-l border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">
          History — {employeeName}
        </h2>
        <button onClick={onClose} className="text-xs text-zinc-500 underline">
          Close
        </button>
      </div>

      <div className="flex gap-2 text-sm">
        <label className="flex flex-1 flex-col gap-1">
          From
          <input
            type="date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            className="rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          To
          <input
            type="date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            className="rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </label>
      </div>

      {loadError && <p className="text-sm text-red-600">{loadError}</p>}
      {loading && <p className="text-sm text-zinc-400">Loading…</p>}

      {!loading && items.length === 0 && !loadError && (
        <p className="text-sm text-zinc-400">No geofence events for this range.</p>
      )}

      <ul className="flex flex-col gap-1">
        {items.map((event) => {
          const isSessionBoundary = event.event_type === "check_in" || event.event_type === "check_out";
          return (
            <li
              key={event.id}
              className={`flex items-center justify-between rounded border px-2 py-1.5 text-sm ${
                isSessionBoundary
                  ? "border-zinc-300 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/60"
                  : "border-zinc-200 dark:border-zinc-800"
              }`}
            >
              <span className="flex flex-col">
                <span
                  className={`font-medium ${
                    isSessionBoundary
                      ? "text-zinc-900 dark:text-zinc-50"
                      : "text-zinc-700 dark:text-zinc-300"
                  }`}
                >
                  {EVENT_TYPE_LABELS[event.event_type] ?? event.event_type}
                </span>
                <span className="text-xs text-zinc-500">{event.geofence_name}</span>
              </span>
              <span className="text-xs text-zinc-500">
                {new Date(event.created_at).toLocaleString()}
              </span>
            </li>
          );
        })}
      </ul>

      {total > HISTORY_PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <button
            onClick={() => load(Math.max(0, offset - HISTORY_PAGE_SIZE))}
            disabled={!hasPrevPage || loading}
            className="text-blue-600 underline disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-xs text-zinc-500">
            {offset + 1}–{Math.min(offset + items.length, total)} of {total}
          </span>
          <button
            onClick={() => load(offset + HISTORY_PAGE_SIZE)}
            disabled={!hasNextPage || loading}
            className="text-blue-600 underline disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}

      <FaceAttemptsSection employeeId={employeeId} dateFrom={dateFrom} dateTo={dateTo} />
    </div>
  );
}

function SiteStatusPageContent() {
  const { user, logout } = useAuth();

  const [exceptions, setExceptions] = useState<AttendanceException[]>([]);
  const [needsAttentionCount, setNeedsAttentionCount] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [rosterExpanded, setRosterExpanded] = useState(false);
  const [selectedEmployee, setSelectedEmployee] = useState<{ id: string; name: string } | null>(
    null,
  );

  // Every employee, checked-in or not — Site Status's roster only ever
  // shows who's currently open (see list_open() on the backend), but a
  // payroll dispute is usually about someone who has already checked out.
  // This is the lookup that makes their history reachable regardless.
  const [allEmployees, setAllEmployees] = useState<Employee[]>([]);
  const [employeeSearch, setEmployeeSearch] = useState("");
  const [showEmployeeSearch, setShowEmployeeSearch] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await listAttendanceExceptions();
      setExceptions(data.items);
      setNeedsAttentionCount(data.needs_attention_count);
      setLastUpdated(new Date());
      setLoadError(null);
    } catch (err) {
      setLoadError(apiErrorMessage(err));
    }
  }, []);

  useEffect(() => {
    // Same react-hooks/set-state-in-effect fix as HistoryPanel above — the
    // interval reference is already a callback (fine, per the rule's own
    // guidance); the immediate first fetch needs the same treatment.
    const initial = setTimeout(load, 0);
    const interval = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
    };
  }, [load]);

  useEffect(() => {
    const timer = setTimeout(() => {
      listEmployees()
        .then(setAllEmployees)
        .catch(() => {
          // Non-critical: only the lookup search degrades, not the whole page.
        });
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  function openHistory(employeeId: string, name: string) {
    setSelectedEmployee({ id: employeeId, name });
  }

  const filteredEmployees = useMemo(() => {
    const q = employeeSearch.trim().toLowerCase();
    if (!q) return [];
    return allEmployees
      .filter(
        (e) =>
          e.employee_code.toLowerCase().includes(q) ||
          e.user.full_name.toLowerCase().includes(q),
      )
      .slice(0, 10);
  }, [allEmployees, employeeSearch]);

  const needsAttention = exceptions.filter((e) => e.needs_attention);
  const notMonitored = exceptions.filter((e) => !e.needs_attention && e.monitoring_status === "not_monitored");
  const roster = exceptions.filter(
    (e) => !e.needs_attention && e.monitoring_status !== "not_monitored",
  );
  const hasStale = roster.some((e) => e.monitoring_status === "stale");

  return (
    <div className="flex flex-1">
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
              Site status — today
            </h1>
            <Link href="/geofences" className="text-sm text-blue-600 underline">
              Geofences
            </Link>
            <Link href="/face-enrollment" className="text-sm text-blue-600 underline">
              Face Enrollment
            </Link>
          </div>
          <div className="flex items-center gap-4 text-sm text-zinc-600 dark:text-zinc-400">
            <button
              onClick={() => setShowEmployeeSearch((v) => !v)}
              className="underline"
            >
              Look up employee history
            </button>
            <span>{user?.full_name} ({user?.role})</span>
            <button onClick={() => logout()} className="underline">
              Sign out
            </button>
          </div>
        </header>

        {showEmployeeSearch && (
          <div className="relative mx-6 mt-4">
            <input
              autoFocus
              placeholder="Search by name or employee code — includes checked-out employees…"
              value={employeeSearch}
              onChange={(e) => setEmployeeSearch(e.target.value)}
              className="w-full max-w-md rounded border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            />
            {filteredEmployees.length > 0 && (
              <ul className="absolute z-10 mt-1 w-full max-w-md rounded border border-zinc-200 bg-white shadow-lg dark:border-zinc-800 dark:bg-zinc-900">
                {filteredEmployees.map((e) => (
                  <li key={e.id}>
                    <button
                      onClick={() => {
                        openHistory(e.id, e.user.full_name);
                        setShowEmployeeSearch(false);
                        setEmployeeSearch("");
                      }}
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

        {loadError && (
          <p className="mx-6 mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
            {loadError}
          </p>
        )}

        <div className="flex flex-col gap-4 p-6">
          {/* Exception-first banner — the one thing a viewer must see first. */}
          <div
            className={`rounded-lg border px-4 py-3 text-sm font-medium ${
              needsAttentionCount > 0
                ? "border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                : "border-green-300 bg-green-50 text-green-800 dark:border-green-900 dark:bg-green-950 dark:text-green-300"
            }`}
          >
            {needsAttentionCount > 0 ? `${needsAttentionCount} need attention` : "All clear"}
            {lastUpdated && (
              <span className="ml-3 text-xs font-normal opacity-70">
                Updated {lastUpdated.toLocaleTimeString()}
              </span>
            )}
          </div>

          {/* Exception rows */}
          {needsAttention.length > 0 && (
            <div className="flex flex-col gap-2">
              <h2 className="text-sm font-medium text-zinc-500">Needs attention</h2>
              {needsAttention.map((row) => (
                <ExceptionRow key={row.attendance_id} row={row} onOpenHistory={openHistory} />
              ))}
            </div>
          )}

          {/* Honest "not monitored" gray group — never hidden, even though
              it isn't an exception (design doc success criteria). */}
          {notMonitored.length > 0 && (
            <div className="flex flex-col gap-2">
              <h2 className="text-sm font-medium text-zinc-500">Not monitored</h2>
              <p className="text-xs text-zinc-400">
                No geofence assigned at check-in, or the assigned geofence was later removed —
                these check-ins have nothing to compare location against.
              </p>
              {notMonitored.map((row) => (
                <ExceptionRow key={row.attendance_id} row={row} onOpenHistory={openHistory} />
              ))}
            </div>
          )}

          {/* Collapsed roster of everyone else, monitored and fine. */}
          {roster.length > 0 && (
            <div className="flex flex-col gap-2">
              <button
                onClick={() => setRosterExpanded((v) => !v)}
                className="w-fit text-sm font-medium text-zinc-500 underline"
              >
                {rosterExpanded ? "Hide" : "Show"} roster ({roster.length})
              </button>
              {rosterExpanded && (
                <>
                  {hasStale && (
                    <p className="text-xs text-zinc-400">
                      A stale signal usually means a phone battery saver or no network coverage.
                      It is not evidence of absence.
                    </p>
                  )}
                  {roster.map((row) => (
                    <ExceptionRow key={row.attendance_id} row={row} onOpenHistory={openHistory} />
                  ))}
                </>
              )}
            </div>
          )}

          {exceptions.length === 0 && !loadError && (
            <p className="text-sm text-zinc-400">No one is checked in right now.</p>
          )}
        </div>
      </div>

      {selectedEmployee && (
        <HistoryPanel
          employeeId={selectedEmployee.id}
          employeeName={selectedEmployee.name}
          onClose={() => setSelectedEmployee(null)}
        />
      )}
    </div>
  );
}

export default function SiteStatusPage() {
  return (
    <RequireAuth allowedRoles={["hr_manager", "admin", "super_admin"]}>
      <SiteStatusPageContent />
    </RequireAuth>
  );
}
