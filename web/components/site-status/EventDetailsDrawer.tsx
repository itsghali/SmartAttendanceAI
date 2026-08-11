import { useRef } from "react";

import { GeofenceEventSummary } from "../../lib/siteStatusService";
import { useFocusTrap } from "./useFocusTrap";

const EVENT_TYPE_LABELS: Record<string, string> = {
  enter: "Entered",
  exit: "Exited",
  return: "Returned",
  check_in: "Checked in",
  check_out: "Checked out",
};

interface EventDetailsDrawerProps {
  event: GeofenceEventSummary | null;
  employeeName: string;
  onClose: () => void;
}

// Stacks over HistoryPanel, does not replace it — HistoryPanel stays open
// underneath (design review's navigation topology). No backdrop: both
// panels are inline side drawers, not modal overlays, so clicking main
// content never closes either — only Escape or the Close control does.
export default function EventDetailsDrawer({
  event,
  employeeName,
  onClose,
}: EventDetailsDrawerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  useFocusTrap(event !== null, containerRef, onClose);

  if (!event) return null;

  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-label={`Event details for ${employeeName}`}
      className="flex w-[300px] flex-col gap-3 overflow-y-auto border-l border-zinc-200 p-4 dark:border-zinc-800"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-zinc-900 dark:text-zinc-50">Event details</h2>
        <button onClick={onClose} className="text-xs text-zinc-500 underline">
          Close
        </button>
      </div>

      <dl className="flex flex-col gap-3 text-sm">
        <div>
          <dt className="text-xs text-zinc-500">Employee</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">{employeeName}</dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">Event</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">
            {EVENT_TYPE_LABELS[event.event_type] ?? event.event_type}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">Geofence</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">{event.geofence_name}</dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">Authorized radius</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">
            {event.authorized_radius_meters != null ? `${event.authorized_radius_meters} m` : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">Detected at</dt>
          <dd className="text-zinc-900 dark:text-zinc-50">
            {new Date(event.created_at).toLocaleString()}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-zinc-500">Event ID</dt>
          <dd className="font-mono text-xs text-zinc-500">{event.id}</dd>
        </div>
      </dl>
    </div>
  );
}
