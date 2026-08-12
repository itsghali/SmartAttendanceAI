"use client";

import { useEffect, useMemo, useState } from "react";
import { AxiosError } from "axios";

import AppHeader from "../../components/AppHeader";
import RequireAuth from "../../components/RequireAuth";
import {
  Employee,
  EmployeeCreate,
  EmployeeStatus,
  EmployeeUpdate,
  createEmployee,
  listEmployees,
  updateEmployee,
  updateEmployeeStatus,
} from "../../lib/employeeService";
import { Department, listDepartments } from "../../lib/departmentService";

const ROLE_OPTIONS = ["employee", "supervisor", "hr_manager", "admin", "super_admin", "auditor"];
const STATUS_OPTIONS: EmployeeStatus[] = ["active", "on_leave", "terminated"];

interface EditDraft {
  job_title: string;
  department_id: string;
  supervisor_id: string;
  phone_number: string;
}

function draftFrom(e: Employee): EditDraft {
  return {
    job_title: e.job_title,
    department_id: e.department_id ?? "",
    supervisor_id: e.supervisor_id ?? "",
    phone_number: e.phone_number,
  };
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function generatePassword(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
  let out = "";
  for (let i = 0; i < 12; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out;
}

const EMPTY_CREATE_DRAFT: EmployeeCreate = {
  email: "",
  full_name: "",
  password: "",
  role_name: "employee",
  department_id: null,
  supervisor_id: null,
  job_title: "",
  phone_number: "",
  hire_date: todayIso(),
};

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
}

function EmployeesPageContent() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [createDraft, setCreateDraft] = useState<EmployeeCreate>(EMPTY_CREATE_DRAFT);
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [statusUpdatingId, setStatusUpdatingId] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listEmployees(), listDepartments()])
      .then(([e, d]) => {
        setEmployees(e);
        setDepartments(d);
      })
      .catch((err) => setLoadError(apiErrorMessage(err)));
  }, []);

  const departmentName = useMemo(() => {
    const byId = new Map(departments.map((d) => [d.id, d.name]));
    return (id: string | null) => (id ? byId.get(id) ?? "Unknown" : "—");
  }, [departments]);

  const employeeName = useMemo(() => {
    const byId = new Map(employees.map((e) => [e.id, e.user.full_name]));
    return (id: string | null) => (id ? byId.get(id) ?? "Unknown" : "—");
  }, [employees]);

  function startEdit(e: Employee) {
    setEditingId(e.id);
    setDraft(draftFrom(e));
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
    const updates: EmployeeUpdate = {
      job_title: draft.job_title,
      department_id: draft.department_id || null,
      supervisor_id: draft.supervisor_id || null,
      phone_number: draft.phone_number,
    };
    try {
      const updated = await updateEmployee(id, updates);
      setEmployees((prev) => prev.map((e) => (e.id === id ? updated : e)));
      cancelEdit();
    } catch (err) {
      setSaveError(apiErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function submitCreate() {
    setCreating(true);
    setCreateError(null);
    try {
      const newEmployee = await createEmployee(createDraft);
      setEmployees((prev) => [...prev, newEmployee]);
      setCreateDraft({ ...EMPTY_CREATE_DRAFT, hire_date: todayIso() });
      setShowCreate(false);
    } catch (err) {
      setCreateError(apiErrorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function changeStatus(e: Employee, status: EmployeeStatus) {
    if (status === e.status) return;
    if (
      status === "terminated" &&
      !window.confirm(
        `Terminate ${e.user.full_name} (${e.employee_code})? This deactivates their login — it does not delete their attendance history.`,
      )
    ) {
      return;
    }
    setStatusUpdatingId(e.id);
    setStatusError(null);
    try {
      const updated = await updateEmployeeStatus(e.id, status);
      setEmployees((prev) => prev.map((emp) => (emp.id === e.id ? updated : emp)));
    } catch (err) {
      setStatusError(`${e.user.full_name}: ${apiErrorMessage(err)}`);
    } finally {
      setStatusUpdatingId(null);
    }
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter(
      (e) =>
        e.user.full_name.toLowerCase().includes(q) ||
        e.user.email.toLowerCase().includes(q) ||
        e.employee_code.toLowerCase().includes(q),
    );
  }, [employees, search]);

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader current="employees" title="Employees" />

      {loadError && (
        <p className="mx-6 mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {loadError}
        </p>
      )}
      {statusError && (
        <p className="mx-6 mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {statusError}
        </p>
      )}

      <div className="flex flex-col gap-4 p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-medium text-zinc-500">
            {filtered.length} of {employees.length} employee{employees.length === 1 ? "" : "s"}
          </h2>
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Search name, email, or code…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-64 rounded border border-zinc-300 px-3 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            />
            <button
              onClick={() => {
                setShowCreate((v) => !v);
                setCreateError(null);
              }}
              className="rounded bg-zinc-900 px-3 py-1.5 text-sm font-medium text-white dark:bg-zinc-50 dark:text-zinc-900"
            >
              {showCreate ? "Cancel" : "+ New employee"}
            </button>
          </div>
        </div>

        {showCreate && (
          <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
            <h3 className="mb-3 text-sm font-medium text-zinc-500">New employee</h3>
            {createError && (
              <p className="mb-3 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
                {createError}
              </p>
            )}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Full name
                <input
                  type="text"
                  value={createDraft.full_name}
                  onChange={(ev) => setCreateDraft({ ...createDraft, full_name: ev.target.value })}
                  className="rounded border border-zinc-300 px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Email
                <input
                  type="email"
                  value={createDraft.email}
                  onChange={(ev) => setCreateDraft({ ...createDraft, email: ev.target.value })}
                  className="rounded border border-zinc-300 px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Phone number
                <input
                  type="tel"
                  value={createDraft.phone_number}
                  onChange={(ev) =>
                    setCreateDraft({ ...createDraft, phone_number: ev.target.value })
                  }
                  className="rounded border border-zinc-300 px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Temporary password
                <div className="flex gap-1">
                  <input
                    type="text"
                    value={createDraft.password}
                    onChange={(ev) =>
                      setCreateDraft({ ...createDraft, password: ev.target.value })
                    }
                    className="w-full rounded border border-zinc-300 px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setCreateDraft({ ...createDraft, password: generatePassword() })
                    }
                    className="whitespace-nowrap rounded border border-zinc-300 px-2 text-xs text-zinc-600 dark:border-zinc-700 dark:text-zinc-400"
                  >
                    Generate
                  </button>
                </div>
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Role
                <select
                  value={createDraft.role_name}
                  onChange={(ev) => setCreateDraft({ ...createDraft, role_name: ev.target.value })}
                  className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Job title
                <input
                  type="text"
                  value={createDraft.job_title}
                  onChange={(ev) => setCreateDraft({ ...createDraft, job_title: ev.target.value })}
                  className="rounded border border-zinc-300 px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Department
                <select
                  value={createDraft.department_id ?? ""}
                  onChange={(ev) =>
                    setCreateDraft({ ...createDraft, department_id: ev.target.value || null })
                  }
                  className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="">Global (none)</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Supervisor
                <select
                  value={createDraft.supervisor_id ?? ""}
                  onChange={(ev) =>
                    setCreateDraft({ ...createDraft, supervisor_id: ev.target.value || null })
                  }
                  className="rounded border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                >
                  <option value="">None</option>
                  {employees.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.user.full_name} ({candidate.employee_code})
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                Hire date
                <input
                  type="date"
                  value={createDraft.hire_date}
                  onChange={(ev) => setCreateDraft({ ...createDraft, hire_date: ev.target.value })}
                  className="rounded border border-zinc-300 px-2 py-1.5 text-sm text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                />
              </label>
            </div>
            <p className="mt-3 text-xs text-zinc-500 dark:text-zinc-400">
              The temporary password is never emailed — the employee resets it via the normal
              forgot-password flow.
            </p>
            <button
              onClick={submitCreate}
              disabled={
                creating ||
                !createDraft.full_name ||
                !createDraft.email ||
                !createDraft.password
              }
              className="mt-3 rounded bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
            >
              {creating ? "Creating…" : "Create employee"}
            </button>
          </div>
        )}

        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full min-w-[1250px] text-left text-sm">
            <thead className="border-b border-zinc-200 bg-zinc-50 text-xs uppercase text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <tr>
                <th className="px-4 py-2">Code</th>
                <th className="px-4 py-2">Name</th>
                <th className="px-4 py-2">Email</th>
                <th className="px-4 py-2">Phone</th>
                <th className="px-4 py-2">Role</th>
                <th className="px-4 py-2">Job title</th>
                <th className="px-4 py-2">Department</th>
                <th className="px-4 py-2">Supervisor</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Hire date</th>
                <th className="px-4 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) =>
                editingId === e.id && draft ? (
                  <tr key={e.id} className="border-b border-zinc-100 bg-blue-50/50 dark:border-zinc-900 dark:bg-blue-950/20">
                    <td className="px-4 py-2 font-mono text-xs text-zinc-500">
                      {e.employee_code}
                    </td>
                    <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">
                      {e.user.full_name}
                    </td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.user.email}</td>
                    <td className="px-4 py-2">
                      <input
                        type="tel"
                        value={draft.phone_number}
                        onChange={(ev) => setDraft({ ...draft, phone_number: ev.target.value })}
                        className="w-32 rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      />
                    </td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.user.role}</td>
                    <td className="px-4 py-2">
                      <input
                        type="text"
                        placeholder="Job title"
                        value={draft.job_title}
                        onChange={(ev) => setDraft({ ...draft, job_title: ev.target.value })}
                        className="w-32 rounded border border-zinc-300 px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      />
                    </td>
                    <td className="px-4 py-2">
                      <select
                        value={draft.department_id}
                        onChange={(ev) => setDraft({ ...draft, department_id: ev.target.value })}
                        className="w-36 rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      >
                        <option value="">Global (none)</option>
                        {departments.map((d) => (
                          <option key={d.id} value={d.id}>
                            {d.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-2">
                      <select
                        value={draft.supervisor_id}
                        onChange={(ev) => setDraft({ ...draft, supervisor_id: ev.target.value })}
                        className="w-36 rounded border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
                      >
                        <option value="">None</option>
                        {employees
                          .filter((candidate) => candidate.id !== e.id)
                          .map((candidate) => (
                            <option key={candidate.id} value={candidate.id}>
                              {candidate.user.full_name} ({candidate.employee_code})
                            </option>
                          ))}
                      </select>
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={
                          e.status === "active"
                            ? "rounded bg-green-50 px-2 py-0.5 text-xs text-green-700 dark:bg-green-950 dark:text-green-300"
                            : e.status === "on_leave"
                              ? "rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                              : "rounded bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                        }
                      >
                        {e.status}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.hire_date}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2 whitespace-nowrap">
                        <button
                          onClick={() => saveEdit(e.id)}
                          disabled={saving}
                          className="rounded bg-zinc-900 px-2 py-1 text-xs font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
                        >
                          {saving ? "Saving…" : "Save"}
                        </button>
                        <button onClick={cancelEdit} className="text-xs text-zinc-500 underline">
                          Cancel
                        </button>
                      </div>
                      {saveError && (
                        <p className="mt-1 max-w-[160px] text-xs text-red-600">{saveError}</p>
                      )}
                    </td>
                  </tr>
                ) : (
                  <tr
                    key={e.id}
                    className="border-b border-zinc-100 last:border-0 dark:border-zinc-900"
                  >
                    <td className="px-4 py-2 font-mono text-xs text-zinc-500">
                      {e.employee_code}
                    </td>
                    <td className="px-4 py-2 text-zinc-900 dark:text-zinc-50">
                      {e.user.full_name}
                    </td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.user.email}</td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                      {e.phone_number || "—"}
                    </td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.user.role}</td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                      {e.job_title || "—"}
                    </td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                      {departmentName(e.department_id)}
                    </td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">
                      {employeeName(e.supervisor_id)}
                    </td>
                    <td className="px-4 py-2">
                      <select
                        value={e.status}
                        disabled={statusUpdatingId === e.id}
                        onChange={(ev) => changeStatus(e, ev.target.value as EmployeeStatus)}
                        className={
                          "rounded px-2 py-0.5 text-xs disabled:opacity-50 " +
                          (e.status === "active"
                            ? "bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300"
                            : e.status === "on_leave"
                              ? "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300"
                              : "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400")
                        }
                      >
                        {STATUS_OPTIONS.map((s) => (
                          <option key={s} value={s}>
                            {s}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-2 text-zinc-600 dark:text-zinc-400">{e.hire_date}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2 whitespace-nowrap">
                        <button
                          onClick={() => startEdit(e)}
                          className="text-xs text-blue-600 underline"
                        >
                          Edit
                        </button>
                        {e.status !== "terminated" && (
                          <button
                            onClick={() => changeStatus(e, "terminated")}
                            disabled={statusUpdatingId === e.id}
                            className="text-xs text-red-600 underline disabled:opacity-50"
                          >
                            Terminate
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ),
              )}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-6 text-center text-zinc-500">
                    No employees found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default function EmployeesPage() {
  return (
    <RequireAuth allowedRoles={["hr_manager", "admin", "super_admin"]}>
      <EmployeesPageContent />
    </RequireAuth>
  );
}
