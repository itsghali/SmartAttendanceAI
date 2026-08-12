"use client";

import { useEffect, useMemo, useState } from "react";

import AppHeader from "../../components/AppHeader";
import RequireAuth from "../../components/RequireAuth";
import { Employee, listEmployees } from "../../lib/employeeService";
import { Department, listDepartments } from "../../lib/departmentService";
import { GeofenceEventSummary } from "../../lib/siteStatusService";
import KpiRow from "../../components/site-status/KpiRow";
import ExceptionsTable from "../../components/site-status/ExceptionsTable";
import HistoryPanel from "../../components/site-status/HistoryPanel";
import EventDetailsDrawer from "../../components/site-status/EventDetailsDrawer";
import { usePollingExceptions } from "../../components/site-status/usePollingExceptions";

// Polling interval for the exceptions list (design doc's "The Assignment" —
// picked here rather than left implicit). Short enough for same-day triage,
// long enough not to hammer the API for a screen that isn't push-driven.
const POLL_INTERVAL_MS = 30_000;

interface SelectedEmployee {
  id: string;
  name: string;
  // Was this employee live (present in the exceptions list) at the moment
  // this panel opened? Only true when it was — determines whether a later
  // disappearance means "their session closed while I was looking" (show
  // the banner) vs. "I opened this via the checked-out-employee lookup,
  // where absence was expected from the start" (never show it).
  wasLiveOnOpen: boolean;
}

function SiteStatusPageContent() {
  const { items: exceptions, needsAttentionCount, lastUpdated, error: loadError, loading, refresh } =
    usePollingExceptions(POLL_INTERVAL_MS);

  const [selectedEmployee, setSelectedEmployee] = useState<SelectedEmployee | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<GeofenceEventSummary | null>(null);

  // Every employee, checked-in or not — the exceptions list only ever shows
  // who's currently open, but a payroll dispute is usually about someone
  // who has already checked out. This is the lookup that makes their
  // history reachable regardless. Also feeds the Department column/filter.
  const [allEmployees, setAllEmployees] = useState<Employee[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [employeeSearch, setEmployeeSearch] = useState("");
  const [showEmployeeSearch, setShowEmployeeSearch] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => {
      Promise.all([listEmployees(), listDepartments()])
        .then(([emps, depts]) => {
          setAllEmployees(emps);
          setDepartments(depts);
        })
        .catch(() => {
          // Non-critical: only the lookup search / department column
          // degrades, not the whole page.
        });
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  const departmentById = useMemo(() => new Map(departments.map((d) => [d.id, d.name])), [departments]);
  const departmentByEmployee = useMemo(() => {
    const map = new Map<string, string>();
    for (const e of allEmployees) {
      map.set(e.id, e.department_id ? departmentById.get(e.department_id) ?? "—" : "—");
    }
    return map;
  }, [allEmployees, departmentById]);

  function openHistory(employeeId: string, name: string) {
    setSelectedEvent(null);
    setSelectedEmployee({
      id: employeeId,
      name,
      wasLiveOnOpen: exceptions.some((e) => e.employee_id === employeeId),
    });
  }

  function closeHistory() {
    setSelectedEvent(null);
    setSelectedEmployee(null);
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

  const selectedException = selectedEmployee
    ? exceptions.find((e) => e.employee_id === selectedEmployee.id) ?? null
    : null;
  const sessionClosed = Boolean(
    selectedEmployee?.wasLiveOnOpen && !selectedException,
  );

  return (
    <div className="flex flex-1">
      <div className="flex flex-1 flex-col">
        <AppHeader
          current="site-status"
          title="Geofence Monitoring"
          subtitle="Who's outside their authorized zone, right now."
          extraActions={
            <>
              <button onClick={refresh} className="underline">
                Refresh
              </button>
              <button onClick={() => setShowEmployeeSearch((v) => !v)} className="underline">
                Look up checked-out employee
              </button>
            </>
          }
        />

        {showEmployeeSearch && (
          <div className="relative mx-6 mt-4">
            <input
              autoFocus
              placeholder="Search by name or employee code — for employees not currently checked in…"
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

        <div className="flex flex-col gap-4 p-6">
          {/* Exception-first banner — the one thing a viewer must see first,
              kept above the KPI row so it keeps its reviewed position. */}
          <div
            aria-live="polite"
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

          <KpiRow
            exceptions={exceptions}
            loading={loading}
            error={loadError !== null}
            onRetry={refresh}
          />

          <ExceptionsTable
            exceptions={exceptions}
            departmentByEmployee={departmentByEmployee}
            onOpenHistory={openHistory}
            loadError={loadError}
          />
        </div>
      </div>

      {selectedEmployee && (
        <HistoryPanel
          employeeId={selectedEmployee.id}
          employeeName={selectedEmployee.name}
          department={departmentByEmployee.get(selectedEmployee.id) ?? "—"}
          currentStatus={selectedException?.monitoring_status ?? null}
          sessionClosed={sessionClosed}
          onClose={closeHistory}
          onOpenEvent={setSelectedEvent}
        />
      )}
      {selectedEmployee && (
        <EventDetailsDrawer
          event={selectedEvent}
          employeeName={selectedEmployee.name}
          onClose={() => setSelectedEvent(null)}
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
