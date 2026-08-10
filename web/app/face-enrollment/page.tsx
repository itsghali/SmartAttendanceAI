"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AxiosError } from "axios";

import RequireAuth from "../../components/RequireAuth";
import { useAuth } from "../../lib/auth-context";
import { Employee, listEmployees } from "../../lib/employeeService";
import { FaceStatus, enrollFace, getFaceStatus } from "../../lib/faceService";

const MAX_PHOTOS = 5;

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
}

interface PendingPhoto {
  file: File;
  previewUrl: string;
}

function FaceEnrollmentPageContent() {
  const { user, logout } = useAuth();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [employeeSearch, setEmployeeSearch] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState<FaceStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);

  const [photos, setPhotos] = useState<PendingPhoto[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [rejected, setRejected] = useState<{ index: number; reason: string }[]>([]);

  useEffect(() => {
    listEmployees()
      .then(setEmployees)
      .catch((err) => setLoadError(apiErrorMessage(err)));
  }, []);

  // Revoke object URLs on unmount / whenever the pending photo set changes,
  // so switching employees or resubmitting doesn't leak blob URLs.
  useEffect(() => {
    return () => {
      photos.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    };
  }, [photos]);

  const filteredEmployees = useMemo(() => {
    const q = employeeSearch.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter(
      (e) =>
        e.employee_code.toLowerCase().includes(q) ||
        e.user.full_name.toLowerCase().includes(q) ||
        e.user.email.toLowerCase().includes(q),
    );
  }, [employees, employeeSearch]);

  const selectedEmployee = employees.find((e) => e.id === selectedId) ?? null;

  async function handleSelectEmployee(id: string) {
    setSelectedId(id);
    setStatus(null);
    setStatusError(null);
    setSubmitError(null);
    setRejected([]);
    photos.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    setPhotos([]);
    setStatusLoading(true);
    try {
      setStatus(await getFaceStatus(id));
    } catch (err) {
      setStatusError(apiErrorMessage(err));
    } finally {
      setStatusLoading(false);
    }
  }

  function handleFilesChosen(fileList: FileList | null) {
    if (!fileList) return;
    const incoming = Array.from(fileList).filter(
      (f) => f.type === "image/jpeg" || f.type === "image/png",
    );
    const combined = [...photos.map((p) => p.file), ...incoming].slice(0, MAX_PHOTOS);
    photos.forEach((p) => URL.revokeObjectURL(p.previewUrl));
    setPhotos(combined.map((file) => ({ file, previewUrl: URL.createObjectURL(file) })));
  }

  function removePhoto(index: number) {
    setPhotos((prev) => {
      URL.revokeObjectURL(prev[index].previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  }

  async function handleEnroll() {
    if (!selectedId || photos.length === 0) return;
    setSubmitting(true);
    setSubmitError(null);
    setRejected([]);
    try {
      const result = await enrollFace(
        selectedId,
        photos.map((p) => p.file),
      );
      setRejected(result.photos_rejected);
      setStatus(await getFaceStatus(selectedId));
      photos.forEach((p) => URL.revokeObjectURL(p.previewUrl));
      setPhotos([]);
    } catch (err) {
      setSubmitError(apiErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center justify-between border-b border-zinc-200 px-6 py-4 dark:border-zinc-800">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            Face Enrollment
          </h1>
          <Link href="/geofences" className="text-sm text-blue-600 underline">
            Geofences
          </Link>
        </div>
        <div className="flex items-center gap-4 text-sm text-zinc-600 dark:text-zinc-400">
          <span>{user?.full_name} ({user?.role})</span>
          <button onClick={() => logout()} className="underline">
            Sign out
          </button>
        </div>
      </header>

      {loadError && (
        <p className="mx-6 mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {loadError}
        </p>
      )}

      <div className="grid flex-1 grid-cols-1 gap-4 p-6 lg:grid-cols-[280px_1fr]">
        {/* Employee list */}
        <div className="flex flex-col gap-2 overflow-y-auto rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
          <input
            placeholder="Search employees…"
            value={employeeSearch}
            onChange={(e) => setEmployeeSearch(e.target.value)}
            className="mb-1 rounded border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
          />
          {filteredEmployees.map((e) => (
            <button
              key={e.id}
              onClick={() => handleSelectEmployee(e.id)}
              className={`flex flex-col gap-0.5 rounded border px-3 py-2 text-left text-sm ${
                e.id === selectedId
                  ? "border-blue-500 bg-blue-50 dark:bg-blue-950"
                  : "border-zinc-200 dark:border-zinc-800"
              }`}
            >
              <span className="font-medium text-zinc-900 dark:text-zinc-50">
                {e.user.full_name}
              </span>
              <span className="text-xs text-zinc-500">
                {e.employee_code} · {e.job_title || "—"}
              </span>
            </button>
          ))}
          {filteredEmployees.length === 0 && (
            <p className="text-sm text-zinc-400">No employees found.</p>
          )}
        </div>

        {/* Enrollment panel */}
        <div className="flex flex-col gap-4">
          {!selectedEmployee && (
            <p className="text-sm text-zinc-500">Select an employee to enroll or update their face.</p>
          )}

          {selectedEmployee && (
            <>
              <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
                <h2 className="text-sm font-medium text-zinc-500">
                  {selectedEmployee.user.full_name} ({selectedEmployee.employee_code})
                </h2>
                {statusLoading && <p className="mt-2 text-sm text-zinc-400">Loading status…</p>}
                {statusError && <p className="mt-2 text-sm text-red-600">{statusError}</p>}
                {status && (
                  <p className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">
                    {status.enrolled
                      ? `Enrolled — ${status.photo_count} photo(s), since ${new Date(status.enrolled_at!).toLocaleDateString()}`
                      : "Not enrolled yet"}
                  </p>
                )}
              </div>

              <div className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
                <label className="flex flex-col gap-2 text-sm">
                  <span className="font-medium text-zinc-500">
                    Photos ({photos.length}/{MAX_PHOTOS}) — clear front-facing photos, one face
                    per photo, jpeg or png
                  </span>
                  <input
                    type="file"
                    accept="image/jpeg,image/png"
                    multiple
                    disabled={photos.length >= MAX_PHOTOS}
                    onChange={(e) => {
                      handleFilesChosen(e.target.files);
                      e.target.value = "";
                    }}
                    className="text-sm"
                  />
                </label>

                {photos.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-3">
                    {photos.map((p, i) => (
                      <div key={p.previewUrl} className="relative">
                        {/* eslint-disable-next-line @next/next/no-img-element -- local blob preview, not a remote/optimizable asset */}
                        <img
                          src={p.previewUrl}
                          alt={`Selected photo ${i + 1}`}
                          className="h-20 w-20 rounded object-cover"
                        />
                        <button
                          type="button"
                          onClick={() => removePhoto(i)}
                          className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-red-600 text-xs text-white"
                          aria-label={`Remove photo ${i + 1}`}
                        >
                          ×
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <button
                  type="button"
                  onClick={handleEnroll}
                  disabled={submitting || photos.length === 0}
                  className="mt-4 rounded bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
                >
                  {submitting ? "Enrolling…" : "Enroll photos"}
                </button>

                {submitError && <p className="mt-2 text-sm text-red-600">{submitError}</p>}
                {rejected.length > 0 && (
                  <div className="mt-2 text-sm text-amber-700 dark:text-amber-400">
                    {rejected.length} photo(s) rejected:
                    <ul className="list-inside list-disc">
                      {rejected.map((r) => (
                        <li key={r.index}>
                          Photo {r.index + 1}: {r.reason.replace(/_/g, " ")}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function FaceEnrollmentPage() {
  return (
    <RequireAuth allowedRoles={["hr_manager", "admin", "super_admin"]}>
      <FaceEnrollmentPageContent />
    </RequireAuth>
  );
}
