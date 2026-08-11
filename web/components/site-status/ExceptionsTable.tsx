import { memo, useMemo, useState } from "react";

import { AttendanceException } from "../../lib/siteStatusService";

const EVENT_TYPE_LABELS: Record<string, string> = {
  enter: "Entered",
  exit: "Exited",
  return: "Returned",
  check_in: "Checked in",
  check_out: "Checked out",
};

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

interface RowProps {
  row: AttendanceException;
  departmentName: string;
  onOpenHistory: (employeeId: string, name: string) => void;
}

const ExceptionTableRow = memo(function ExceptionTableRow({
  row,
  departmentName,
  onOpenHistory,
}: RowProps) {
  return (
    <tr
      onClick={() => onOpenHistory(row.employee_id, row.employee_full_name)}
      className="cursor-pointer border-b border-zinc-100 text-sm last:border-0 hover:bg-zinc-50 dark:border-zinc-900 dark:hover:bg-zinc-900"
    >
      <td className="px-3 py-2">
        <div className="flex flex-col">
          <span className="font-medium text-zinc-900 dark:text-zinc-50">
            {row.employee_full_name}
          </span>
          <span className="text-xs text-zinc-500">{row.employee_code}</span>
        </div>
      </td>
      <td className="px-3 py-2 text-zinc-700 dark:text-zinc-300">{departmentName}</td>
      <td className="px-3 py-2 text-zinc-700 dark:text-zinc-300">
        {row.last_event_type ? EVENT_TYPE_LABELS[row.last_event_type] ?? row.last_event_type : "—"}
      </td>
      <td className="px-3 py-2 text-zinc-700 dark:text-zinc-300">{row.geofence_name ?? "—"}</td>
      <td className="px-3 py-2 text-zinc-500">
        {row.last_event_at ? new Date(row.last_event_at).toLocaleTimeString() : "—"}
      </td>
      <td className="px-3 py-2">
        <span className={`rounded px-2 py-0.5 text-xs font-medium ${statusBadgeClass(row.monitoring_status)}`}>
          {statusLabel(row.monitoring_status)}
        </span>
      </td>
    </tr>
  );
});

function GroupTable({
  rows,
  departmentByEmployee,
  onOpenHistory,
}: {
  rows: AttendanceException[];
  departmentByEmployee: Map<string, string>;
  onOpenHistory: (employeeId: string, name: string) => void;
}) {
  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="border-b border-zinc-200 text-left text-xs text-zinc-500 dark:border-zinc-800">
          <th className="px-3 py-1.5 font-medium">Employee</th>
          <th className="px-3 py-1.5 font-medium">Department</th>
          <th className="px-3 py-1.5 font-medium">Event</th>
          <th className="px-3 py-1.5 font-medium">Geofence</th>
          <th className="px-3 py-1.5 font-medium">Detected at</th>
          <th className="px-3 py-1.5 font-medium">Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <ExceptionTableRow
            key={row.attendance_id}
            row={row}
            departmentName={departmentByEmployee.get(row.employee_id) ?? "—"}
            onOpenHistory={onOpenHistory}
          />
        ))}
      </tbody>
    </table>
  );
}

interface ExceptionsTableProps {
  exceptions: AttendanceException[];
  departmentByEmployee: Map<string, string>;
  onOpenHistory: (employeeId: string, name: string) => void;
  loadError: string | null;
}

// Keeps the existing 3-group exception-first structure (needs-attention /
// not-monitored / roster) — a deliberate, previously-reviewed decision —
// and applies real `<table>` styling within each group rather than
// replacing the grouping with one flat sortable table.
export default function ExceptionsTable({
  exceptions,
  departmentByEmployee,
  onOpenHistory,
  loadError,
}: ExceptionsTableProps) {
  const [search, setSearch] = useState("");
  const [departmentFilter, setDepartmentFilter] = useState<string>("");
  const [rosterExpanded, setRosterExpanded] = useState(false);

  // Filter precedence, stated explicitly per eng review: group membership
  // is computed first from unfiltered data, search/department filters
  // apply within each group afterward, default sort applies last.
  const { needsAttention, notMonitored, roster } = useMemo(() => {
    const na = exceptions.filter((e) => e.needs_attention);
    const nm = exceptions.filter((e) => !e.needs_attention && e.monitoring_status === "not_monitored");
    const rest = exceptions.filter(
      (e) => !e.needs_attention && e.monitoring_status !== "not_monitored",
    );
    // Stable sort (JS Array.prototype.sort is stable per spec) — re-running
    // this on a poll tick with mostly-unchanged check_in_at values does not
    // reshuffle rows whose relative order hasn't actually changed.
    na.sort((a, b) => a.check_in_at.localeCompare(b.check_in_at));
    return { needsAttention: na, notMonitored: nm, roster: rest };
  }, [exceptions]);

  const q = search.trim().toLowerCase();
  const matchesFilters = (row: AttendanceException) => {
    const matchesSearch =
      !q ||
      row.employee_full_name.toLowerCase().includes(q) ||
      row.employee_code.toLowerCase().includes(q);
    const matchesDept =
      !departmentFilter || departmentByEmployee.get(row.employee_id) === departmentFilter;
    return matchesSearch && matchesDept;
  };

  const filteredNeedsAttention = needsAttention.filter(matchesFilters);
  const filteredNotMonitored = notMonitored.filter(matchesFilters);
  const filteredRoster = roster.filter(matchesFilters);
  const hasStale = filteredRoster.some((e) => e.monitoring_status === "stale");

  const filtersActive = q.length > 0 || departmentFilter.length > 0;
  const totalUnfiltered = exceptions.length;
  const totalFiltered =
    filteredNeedsAttention.length + filteredNotMonitored.length + filteredRoster.length;

  const departmentOptions = useMemo(
    () => Array.from(new Set(departmentByEmployee.values())).sort(),
    [departmentByEmployee],
  );

  if (loadError) {
    return (
      <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
        {loadError}
      </p>
    );
  }

  if (totalUnfiltered === 0) {
    return <p className="text-sm text-zinc-400">No one is checked in right now.</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <input
          placeholder="Search employee name or code…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="w-64 rounded border border-zinc-300 px-3 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <select
          value={departmentFilter}
          onChange={(e) => setDepartmentFilter(e.target.value)}
          className="rounded border border-zinc-300 px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        >
          <option value="">All departments</option>
          {departmentOptions.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        {filtersActive && (
          <button
            onClick={() => {
              setSearch("");
              setDepartmentFilter("");
            }}
            className="text-sm text-blue-600 underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {filtersActive && totalFiltered === 0 ? (
        <p className="text-sm text-zinc-400">
          No results match your filters. <button onClick={() => { setSearch(""); setDepartmentFilter(""); }} className="text-blue-600 underline">Clear filters</button>
        </p>
      ) : (
        <>
          {filteredNeedsAttention.length > 0 && (
            <div className="flex flex-col gap-2">
              <h2 className="text-sm font-medium text-zinc-500">Needs attention</h2>
              <GroupTable
                rows={filteredNeedsAttention}
                departmentByEmployee={departmentByEmployee}
                onOpenHistory={onOpenHistory}
              />
            </div>
          )}

          {filteredNotMonitored.length > 0 && (
            <div className="flex flex-col gap-2">
              <h2 className="text-sm font-medium text-zinc-500">Not monitored</h2>
              <p className="text-xs text-zinc-400">
                No geofence assigned at check-in, or the assigned geofence was later removed —
                these check-ins have nothing to compare location against.
              </p>
              <GroupTable
                rows={filteredNotMonitored}
                departmentByEmployee={departmentByEmployee}
                onOpenHistory={onOpenHistory}
              />
            </div>
          )}

          {filteredRoster.length > 0 && (
            <div className="flex flex-col gap-2">
              <button
                onClick={() => setRosterExpanded((v) => !v)}
                className="w-fit text-sm font-medium text-zinc-500 underline"
              >
                {rosterExpanded ? "Hide" : "Show"} roster ({filteredRoster.length})
              </button>
              {rosterExpanded && (
                <>
                  {hasStale && (
                    <p className="text-xs text-zinc-400">
                      A stale signal usually means a phone battery saver or no network coverage.
                      It is not evidence of absence.
                    </p>
                  )}
                  <GroupTable
                    rows={filteredRoster}
                    departmentByEmployee={departmentByEmployee}
                    onOpenHistory={onOpenHistory}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
