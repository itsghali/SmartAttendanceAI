import { useCallback, useEffect, useRef, useState } from "react";
import { AxiosError } from "axios";

import { AttendanceException, listAttendanceExceptions } from "../../lib/siteStatusService";

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
}

// Same fields the UI actually renders — a change here is a real change,
// a difference elsewhere (there isn't one today, but future-proofs this)
// would still not warrant a re-render of an otherwise-identical row.
function rowsEqual(a: AttendanceException, b: AttendanceException): boolean {
  return (
    a.monitoring_status === b.monitoring_status &&
    a.needs_attention === b.needs_attention &&
    a.last_event_type === b.last_event_type &&
    a.last_event_at === b.last_event_at &&
    a.geofence_name === b.geofence_name &&
    a.employee_full_name === b.employee_full_name &&
    a.employee_code === b.employee_code &&
    a.check_in_at === b.check_in_at
  );
}

// Merge by attendance_id, preserving object identity for unchanged rows —
// lets React.memo'd row components skip re-rendering on a poll tick where
// their own data didn't change (eng review's "no flicker" requirement).
function mergeExceptions(
  prev: AttendanceException[],
  next: AttendanceException[],
): AttendanceException[] {
  const prevById = new Map(prev.map((e) => [e.attendance_id, e]));
  return next.map((item) => {
    const old = prevById.get(item.attendance_id);
    return old && rowsEqual(old, item) ? old : item;
  });
}

export interface PollingExceptionsState {
  items: AttendanceException[];
  needsAttentionCount: number;
  lastUpdated: Date | null;
  error: string | null;
  loading: boolean;
}

export function usePollingExceptions(intervalMs: number): PollingExceptionsState & {
  refresh: () => Promise<void>;
} {
  const [state, setState] = useState<PollingExceptionsState>({
    items: [],
    needsAttentionCount: 0,
    lastUpdated: null,
    error: null,
    loading: true,
  });
  const itemsRef = useRef<AttendanceException[]>([]);
  // Monotonic request counter — a poll response that arrives after a
  // newer request has already started is discarded, not applied. Same
  // idempotency shape this codebase already uses server-side for
  // geofence-ping ping_seq.
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const data = await listAttendanceExceptions();
      if (seq !== requestSeq.current) return;
      const merged = mergeExceptions(itemsRef.current, data.items);
      itemsRef.current = merged;
      setState({
        items: merged,
        needsAttentionCount: data.needs_attention_count,
        lastUpdated: new Date(),
        error: null,
        loading: false,
      });
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setState((s) => ({ ...s, error: apiErrorMessage(err), loading: false }));
    }
  }, []);

  useEffect(() => {
    const initial = setTimeout(load, 0);
    const interval = setInterval(load, intervalMs);
    return () => {
      clearTimeout(initial);
      clearInterval(interval);
    };
  }, [load, intervalMs]);

  return { ...state, refresh: load };
}
