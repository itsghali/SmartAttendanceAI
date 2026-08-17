import { GeofenceEventSummary } from "../../lib/siteStatusService";

// Extracted as a pure function (same rationale as kpi.ts) so it's
// unit-testable without dragging in HistoryPanel's API-client import chain.
export function formatExitDuration(event: GeofenceEventSummary, nowMs: number): string | null {
  if (event.event_type !== "exit") return null;
  if (event.still_open) {
    const elapsedMinutes = Math.max(
      0,
      Math.floor((nowMs - new Date(event.created_at).getTime()) / 60_000),
    );
    return `still outside ${elapsedMinutes}m`;
  }
  if (event.duration_minutes != null) {
    return `${event.duration_minutes}m`;
  }
  return null;
}
