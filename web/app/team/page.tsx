"use client";

import { useEffect, useMemo, useState } from "react";
import { AxiosError } from "axios";

import RequireAuth from "../../components/RequireAuth";
import { useAuth } from "../../lib/auth-context";
import { Employee, listEmployees } from "../../lib/employeeService";
import {
  Attendance,
  AttendanceCorrection,
  AttendanceStatus,
  correctAttendance,
  listAttendance,
} from "../../lib/attendanceService";

const STATUS_OPTIONS: AttendanceStatus[] = ["present", "late", "remote"];

interface EditDraft {
  check_in_at: string;
  check_out_at: string;
  status: AttendanceStatus;
  notes: string;
}

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
}

// datetime-local inputs read/write local time with no timezone suffix — the
// browser already interprets that as local time on both ends, so converting
// through Date (not string-slicing the UTC ISO value) is what keeps an
// edited timestamp meaning what the supervisor actually typed.
function toLocalInputValue(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fromLocalInputValue(value: string): string {
  return new Date(value).toISOString();
}

function TeamPageContent() {
  const { user, logout } = useAuth();

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [attendance, setAttendance] = useState<Attendance[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([listEmployees(), listAttendance()])
      .then(([e, a]) => {
        setEmployees(e);
        setAttendance(a.items);
      })
      .catch((err) => setLoadError(apiErrorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  const employeeName = useMemo(() => {
    const byId = new Map(employees.map((e) => [e.id, e]));
    return (id: string) => byId.get(id);
  }, [employees]);

  function startEdit(a: Attendance) {
    setEditingId(a.id);
    setDraft({
      check_in_at: toLocalInputValue(a.check_in_at),
      check_out_at: a.check_out_at ? toLocalInputValue(a.check_out_at) : "",
      status: a.status,
      notes: a.notes,
    });
    setSaveError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setDraft(null);
    setSaveError(null);
  }

  async function saveEdit(id: string) {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    const correction: AttendanceCorrection = {
      check_in_at: fromLocalInputValue(draft.check_in_at),
      check_out_at: draft.check_out_at ? fromLocalInputValue(draft.check_out_at) : null,
      status: draft.status,
      notes: draft.notes,
    };
    try {
      const updated = await correctAttendance(id, correction);
      setAttendance((prev) => prev.map((a) => (a.id === id ? updated : a)));
      cancelEdit();
    } catch (err) {
      setSaveError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">My Team</h1>
        <div className="flex items-center gap-4 text-sm text-zinc-600 dark:text-zinc-400">
          <span>{user?.full_name} ({user?.role})</span>
          <button onClick={() => logout()} className="underline">
            Sign out
          </button>
        </div>
      </header>

      {loading && <p className="px-6 py-4 text-sm text-zinc-500">Loading team…</p>}
      {loadError && (
        <p className="mx-6 mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {loadError}
        </p>
      )}

      {!loading && !loadError && (
        <div className="flex flex-col gap-6 p-6">
          <section>
            <h2 className="mb-2 text-sm font-medium text-zinc-500">
              {employees.length} employee{employees.length === 1 ? "" : "s"} in your department
            </h2>
            <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[900px] text-left text-sm">
                <thead className="border-b border-zinc-200 bg-zinc-50 text-xs uppercase text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                  <tr>
                    <th className="px-4 py-2">Code</th>
                    <th className="px-4 py-2">Name</th>
                    <th className="px-4 py-2">Email</th>
                    <th className="px-4 py-2">Job title</th>
                    <th className="px-4 py-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {employees.map((e) => (
                    <tr key={e.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                      <td className="px-4 py-2 font-mono text-xs text-zinc-500">{e.employee_code}</td>
                      <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">{e.user.full_name}</td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.user.email}</td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.job_title || "—"}</td>
                      <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.status}</td>
                    </tr>
                  ))}
                  {employees.length === 0 && (
                    <tr>
                      <td colSpan={5} className="px-4 py-6 text-center text-zinc-500">
                        No employees in your department yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-sm font-medium text-zinc-500">
              {attendance.length} attendance record{attendance.length === 1 ? "" : "s"}
            </h2>
            {saveError && (
              <p className="mb-2 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
                {saveError}
              </p>
            )}
            <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full min-w-[1000px] text-left text-sm">
                <thead className="border-b border-zinc-200 bg-zinc-50 text-xs uppercase text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
                  <tr>
                    <th className="px-4 py-2">Employee</th>
                    <th className="px-4 py-2">Date</th>
                    <th className="px-4 py-2">Check-in</th>
                    <th className="px-4 py-2">Check-out</th>
                    <th className="px-4 py-2">Status</th>
                    <th className="px-4 py-2">Notes</th>
                    <th className="px-4 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {attendance.map((a) =>
                    editingId === a.id && draft ? (
                      <tr key={a.id} className="border-b border-zinc-100 bg-blue-50/50 dark:border-zinc-900 dark:bg-blue-950/20">
                        <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">
                          {employeeName(a.employee_id)?.user.full_name ?? "Unknown"}
                        </td>
                        <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{a.attendance_date}</td>
                        <td className="px-4 py-2">
                          <input
                            type="datetime-local"
                            value={draft.check_in_at}
                            onChange={(ev) => setDraft({ ...draft, check_in_at: ev.target.value })}
                            className="rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                          />
                        </td>
                        <td className="px-4 py-2">
                          <input
                            type="datetime-local"
                            value={draft.check_out_at}
                            onChange={(ev) => setDraft({ ...draft, check_out_at: ev.target.value })}
                            className="rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                          />
                        </td>
                        <td className="px-4 py-2">
                          <select
                            value={draft.status}
                            onChange={(ev) => setDraft({ ...draft, status: ev.target.value as AttendanceStatus })}
                            className="rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                          >
                            {STATUS_OPTIONS.map((s) => (
                              <option key={s} value={s}>
                                {s}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td className="px-4 py-2">
                          <input
                            type="text"
                            value={draft.notes}
                            onChange={(ev) => setDraft({ ...draft, notes: ev.target.value })}
                            className="w-40 rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                          />
                        </td>
                        <td className="px-4 py-2">
                          <div className="flex items-center gap-2 whitespace-nowrap">
                            <button
                              onClick={() => saveEdit(a.id)}
                              disabled={saving}
                              className="rounded bg-zinc-900 px-2 py-1 text-xs font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
                            >
                              {saving ? "Saving…" : "Save"}
                            </button>
                            <button onClick={cancelEdit} className="text-xs text-zinc-500 underline">
                              Cancel
                            </button>
                          </div>
                        </td>
                      </tr>
                    ) : (
                      <tr key={a.id} className="border-b border-zinc-100 last:border-0 dark:border-zinc-900">
                        <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">
                          {employeeName(a.employee_id)?.user.full_name ?? "Unknown"}
                        </td>
                        <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{a.attendance_date}</td>
                        <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                          {new Date(a.check_in_at).toLocaleString()}
                        </td>
                        <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                          {a.check_out_at ? new Date(a.check_out_at).toLocaleString() : "—"}
                        </td>
                        <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{a.status}</td>
                        <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{a.notes || "—"}</td>
                        <td className="px-4 py-2">
                          <button onClick={() => startEdit(a)} className="text-xs text-blue-600 underline">
                            Correct
                          </button>
                        </td>
                      </tr>
                    ),
                  )}
                  {attendance.length === 0 && (
                    <tr>
                      <td colSpan={7} className="px-4 py-6 text-center text-zinc-500">
                        No attendance records yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

export default function TeamPage() {
  return (
    <RequireAuth allowedRoles={["supervisor"]}>
      <TeamPageContent />
    </RequireAuth>
  );
}
