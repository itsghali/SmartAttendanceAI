import { useCallback, useEffect, useRef, useState } from "react";
import { AxiosError } from "axios";

import {
  FaceVerificationAttempt,
  GeofenceEventSummary,
  getEmployeeFaceAttempts,
  getEmployeeGeofenceHistory,
} from "../../lib/siteStatusService";
import { useFocusTrap } from "./useFocusTrap";

const HISTORY_PAGE_SIZE = 50;

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
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

interface HistoryPanelProps {
  employeeId: string;
  employeeName: string;
  department: string;
  currentStatus: string | null;
  sessionClosed: boolean;
  onClose: () => void;
  onOpenEvent: (event: GeofenceEventSummary) => void;
}

// Today's overview + profile header + timeline. Escape closes this panel
// only when it's the topmost open panel — if EventDetailsDrawer is open on
// top, that consumes Escape first (useFocusTrap's stack).
export default function HistoryPanel({
  employeeId,
  employeeName,
  department,
  currentStatus,
  sessionClosed,
  onClose,
  onOpenEvent,
}: HistoryPanelProps) {
  const [items, setItems] = useState<GeofenceEventSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  useFocusTrap(true, containerRef, onClose);

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
    const timer = setTimeout(() => load(0), 0);
    return () => clearTimeout(timer);
  }, [load]);

  const hasNextPage = offset + items.length < total;
  const hasPrevPage = offset > 0;

  const todayExitsCount = items.filter(
    (e) => e.event_type === "exit" && new Date(e.created_at).toDateString() === new Date().toDateString(),
  ).length;
  const lastEvent = items[0] ?? null;

  const initials = employeeName
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-label={`History for ${employeeName}`}
      className="flex w-[380px] flex-col gap-3 overflow-y-auto border-l border-zinc-200 p-4 dark:border-zinc-800"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-full bg-zinc-200 text-sm font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
            {initials}
          </span>
          <div className="flex flex-col">
            <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">{employeeName}</h2>
            <span className="text-xs text-zinc-500">{department}</span>
          </div>
        </div>
        <button onClick={onClose} className="text-xs text-zinc-500 underline">
          Close
        </button>
      </div>

      {sessionClosed && (
        <p className="rounded bg-zinc-100 px-3 py-2 text-xs text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
          This session has closed — the employee checked out since this panel opened.
        </p>
      )}

      <div className="grid grid-cols-2 gap-2 rounded border border-zinc-200 p-3 text-xs dark:border-zinc-800">
        <div>
          <div className="text-zinc-500">Current status</div>
          <div className="font-medium text-zinc-900 dark:text-zinc-50">{currentStatus ?? "—"}</div>
        </div>
        <div>
          <div className="text-zinc-500">Exits today</div>
          <div className="font-medium text-zinc-900 dark:text-zinc-50">{todayExitsCount}</div>
        </div>
        <div className="col-span-2">
          <div className="text-zinc-500">Last event</div>
          <div className="font-medium text-zinc-900 dark:text-zinc-50">
            {lastEvent
              ? `${EVENT_TYPE_LABELS[lastEvent.event_type] ?? lastEvent.event_type} — ${new Date(lastEvent.created_at).toLocaleString()}`
              : "—"}
          </div>
        </div>
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
        {items.map((event, idx) => {
          const isSessionBoundary = event.event_type === "check_in" || event.event_type === "check_out";
          const prevDay = idx > 0 ? new Date(items[idx - 1].created_at).toDateString() : null;
          const thisDay = new Date(event.created_at).toDateString();
          const showDateDivider = idx === 0 || prevDay !== thisDay;
          const dotClass = isSessionBoundary
            ? "bg-zinc-500"
            : event.event_type === "exit"
              ? "bg-red-500"
              : event.event_type === "return"
                ? "bg-blue-500"
                : "bg-green-500";
          return (
            <li key={event.id}>
              {showDateDivider && (
                <div className="mt-2 mb-1 text-xs font-medium text-zinc-400">{thisDay}</div>
              )}
              <button
                onClick={() => onOpenEvent(event)}
                className={`flex w-full items-center gap-2 rounded border px-2 py-1.5 text-left text-sm ${
                  isSessionBoundary
                    ? "border-zinc-300 bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900/60"
                    : "ml-3 border-zinc-200 dark:border-zinc-800"
                }`}
              >
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
                <span className="flex flex-1 flex-col">
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
                  {new Date(event.created_at).toLocaleTimeString()}
                </span>
              </button>
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
