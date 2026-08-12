"use client";

import { useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { AxiosError } from "axios";

import AppHeader from "../../components/AppHeader";
import RequireAuth from "../../components/RequireAuth";
import {
  AssignedEmployee,
  BoundaryType,
  Geofence,
  assignEmployee,
  createGeofence,
  listAssignedEmployees,
  listGeofences,
  setGeofenceActive,
  unassignEmployee,
  updateGeofence,
} from "../../lib/geofenceService";
import { Employee, listEmployees } from "../../lib/employeeService";
import { Department, listDepartments } from "../../lib/departmentService";

// Leaflet touches `window` at import time — must stay out of the server bundle.
const GeofenceMap = dynamic(() => import("../../components/GeofenceMap"), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-zinc-500">Loading map…</div>
  ),
});

const MIN_POLYGON_POINTS = 3;

function apiErrorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = (err.response?.data as { detail?: string } | undefined)?.detail;
    if (detail) return detail;
  }
  return "Something went wrong";
}

function GeofencesPageContent() {
  const [geofences, setGeofences] = useState<Geofence[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [departmentId, setDepartmentId] = useState<string>("");
  const [boundaryType, setBoundaryType] = useState<BoundaryType>("circle");
  const [circleCenter, setCircleCenter] = useState<[number, number] | null>(null);
  const [radiusMeters, setRadiusMeters] = useState(100);
  const [polygonPoints, setPolygonPoints] = useState<[number, number][]>([]);
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [focusPoint, setFocusPoint] = useState<[number, number] | null>(null);
  const [focusToken, setFocusToken] = useState(0);
  const [toggleError, setToggleError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [assigned, setAssigned] = useState<AssignedEmployee[]>([]);
  const [employeeSearch, setEmployeeSearch] = useState("");
  const [assignError, setAssignError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listGeofences(), listDepartments(), listEmployees()])
      .then(([g, d, e]) => {
        setGeofences(g);
        setDepartments(d);
        setEmployees(e);
      })
      .catch((err) => setLoadError(apiErrorMessage(err)));
  }, []);

  async function refreshGeofences() {
    setGeofences(await listGeofences());
  }

  async function handleSelectGeofence(id: string) {
    setSelectedId(id);
    setAssignError(null);
    try {
      setAssigned(await listAssignedEmployees(id));
    } catch (err) {
      setAssignError(apiErrorMessage(err));
    }
  }

  function resetDraft() {
    setEditingId(null);
    setName("");
    setDepartmentId("");
    setBoundaryType("circle");
    setCircleCenter(null);
    setRadiusMeters(100);
    setPolygonPoints([]);
  }

  function handleEdit(g: Geofence) {
    setCreateError(null);
    setEditingId(g.id);
    setName(g.name);
    setDepartmentId(g.department_id ?? "");
    setBoundaryType(g.boundary_type);
    if (g.boundary_type === "circle") {
      const center: [number, number] | null =
        g.center_latitude != null && g.center_longitude != null
          ? [g.center_latitude, g.center_longitude]
          : null;
      setCircleCenter(center);
      setRadiusMeters(g.radius_meters ?? 100);
      setPolygonPoints([]);
      setFocusPoint(center);
    } else {
      const points = (g.polygon_points ?? []).map<[number, number]>((p) => [
        p.latitude,
        p.longitude,
      ]);
      setPolygonPoints(points);
      setCircleCenter(null);
      setFocusPoint(points[0] ?? null);
    }
    setFocusToken((t) => t + 1);
  }

  async function handleSave() {
    setCreateError(null);
    if (!name.trim()) {
      setCreateError("Name is required");
      return;
    }
    if (boundaryType === "circle" && !circleCenter) {
      setCreateError("Click the map (or enter coordinates) to place the center");
      return;
    }
    if (boundaryType === "polygon" && polygonPoints.length < MIN_POLYGON_POINTS) {
      setCreateError(`Add at least ${MIN_POLYGON_POINTS} points (click the map or type coordinates)`);
      return;
    }

    const geometryFields =
      boundaryType === "circle"
        ? {
            center_latitude: circleCenter![0],
            center_longitude: circleCenter![1],
            radius_meters: radiusMeters,
            polygon_points: null,
          }
        : {
            center_latitude: null,
            center_longitude: null,
            radius_meters: null,
            polygon_points: polygonPoints.map(([latitude, longitude]) => ({
              latitude,
              longitude,
            })),
          };

    setCreating(true);
    try {
      const saved = editingId
        ? await updateGeofence(editingId, {
            name: name.trim(),
            department_id: departmentId || null,
            boundary_type: boundaryType,
            ...geometryFields,
          })
        : await createGeofence({
            name: name.trim(),
            department_id: departmentId || null,
            boundary_type: boundaryType,
            ...geometryFields,
          });
      resetDraft();
      await refreshGeofences();
      await handleSelectGeofence(saved.id);
    } catch (err) {
      setCreateError(apiErrorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(g: Geofence) {
    setToggleError(null);
    try {
      await setGeofenceActive(g.id, !g.is_active);
      await refreshGeofences();
    } catch (err) {
      setToggleError(`${g.name}: ${apiErrorMessage(err)}`);
    }
  }

  async function handleAssign(employeeId: string) {
    if (!selectedId) return;
    setAssignError(null);
    try {
      await assignEmployee(selectedId, employeeId);
      setAssigned(await listAssignedEmployees(selectedId));
    } catch (err) {
      setAssignError(apiErrorMessage(err));
    }
  }

  async function handleUnassign(employeeId: string) {
    if (!selectedId) return;
    setAssignError(null);
    try {
      await unassignEmployee(selectedId, employeeId);
      setAssigned(await listAssignedEmployees(selectedId));
    } catch (err) {
      setAssignError(apiErrorMessage(err));
    }
  }

  const assignedIds = useMemo(() => new Set(assigned.map((e) => e.id)), [assigned]);
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

  const selectedGeofence = geofences.find((g) => g.id === selectedId) ?? null;

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader current="geofences" title="Geofences" />

      {loadError && (
        <p className="mx-6 mt-4 rounded bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">
          {loadError}
        </p>
      )}

      <div className="grid flex-1 grid-cols-1 gap-4 p-6 lg:grid-cols-[280px_1fr_320px]">
        {/* Geofence list */}
        <div className="flex flex-col gap-2 overflow-y-auto rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
          <h2 className="mb-1 text-sm font-medium text-zinc-500">Sites ({geofences.length})</h2>
          {toggleError && <p className="text-xs text-red-600">{toggleError}</p>}
          {geofences.map((g) => (
            <button
              key={g.id}
              onClick={() => handleSelectGeofence(g.id)}
              className={`flex flex-col gap-0.5 rounded border px-3 py-2 text-left text-sm ${
                g.id === selectedId
                  ? "border-blue-500 bg-blue-50 dark:bg-blue-950"
                  : "border-zinc-200 dark:border-zinc-800"
              }`}
            >
              <span className="font-medium text-zinc-900 dark:text-zinc-50">{g.name}</span>
              <span className="text-xs text-zinc-500">
                {g.boundary_type} · {g.is_active ? "active" : "inactive"}
              </span>
              <span className="mt-1 flex w-fit gap-3 text-xs">
                <span
                  role="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleEdit(g);
                  }}
                  className="text-blue-600 underline"
                >
                  Edit
                </span>
                <span
                  role="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleToggleActive(g);
                  }}
                  className="text-blue-600 underline"
                >
                  {g.is_active ? "Deactivate" : "Activate"}
                </span>
              </span>
            </button>
          ))}
          {geofences.length === 0 && (
            <p className="text-sm text-zinc-400">No geofences yet.</p>
          )}
        </div>

        {/* Map + create form */}
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
            <div className="flex w-full items-center justify-between">
              <span className="text-sm font-medium text-zinc-500">
                {editingId ? `Editing — ${name || "untitled"}` : "New geofence"}
              </span>
              {editingId && (
                <button type="button" onClick={resetDraft} className="text-xs text-zinc-500 underline">
                  Cancel edit
                </button>
              )}
            </div>
            <label className="flex flex-col gap-1 text-sm">
              Name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Department (optional)
              <select
                value={departmentId}
                onChange={(e) => setDepartmentId(e.target.value)}
                className="rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
              >
                <option value="">Global (all departments)</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Shape
              <select
                value={boundaryType}
                onChange={(e) => {
                  setBoundaryType(e.target.value as BoundaryType);
                  setCircleCenter(null);
                  setPolygonPoints([]);
                }}
                className="rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
              >
                <option value="circle">Circle</option>
                <option value="polygon">Polygon</option>
              </select>
            </label>
            {boundaryType === "circle" && (
              <>
                <label className="flex flex-col gap-1 text-sm">
                  Center latitude
                  <input
                    type="number"
                    step="any"
                    value={circleCenter?.[0] ?? ""}
                    onChange={(e) =>
                      setCircleCenter([Number(e.target.value), circleCenter?.[1] ?? 0])
                    }
                    className="w-32 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  Center longitude
                  <input
                    type="number"
                    step="any"
                    value={circleCenter?.[1] ?? ""}
                    onChange={(e) =>
                      setCircleCenter([circleCenter?.[0] ?? 0, Number(e.target.value)])
                    }
                    className="w-32 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
                  />
                </label>
                <label className="flex flex-col gap-1 text-sm">
                  Radius (m)
                  <input
                    type="number"
                    min={1}
                    value={radiusMeters}
                    onChange={(e) => setRadiusMeters(Number(e.target.value))}
                    className="w-24 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
                  />
                </label>
              </>
            )}
            {boundaryType === "polygon" && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-zinc-500">{polygonPoints.length} point(s)</span>
                <button
                  type="button"
                  onClick={() => setPolygonPoints((p) => p.slice(0, -1))}
                  disabled={polygonPoints.length === 0}
                  className="text-blue-600 underline disabled:opacity-40"
                >
                  Undo last point
                </button>
                <button
                  type="button"
                  onClick={() => setPolygonPoints([])}
                  disabled={polygonPoints.length === 0}
                  className="text-blue-600 underline disabled:opacity-40"
                >
                  Clear
                </button>
              </div>
            )}
            <button
              type="button"
              onClick={handleSave}
              disabled={creating}
              className="rounded bg-zinc-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-zinc-900"
            >
              {creating ? "Saving…" : editingId ? "Update geofence" : "Save geofence"}
            </button>
            {createError && <p className="w-full text-sm text-red-600">{createError}</p>}

            {boundaryType === "polygon" && polygonPoints.length > 0 && (
              <div className="flex w-full flex-col gap-1">
                {polygonPoints.map(([lat, lng], i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <span className="w-5 text-zinc-500">{i + 1}.</span>
                    <input
                      type="number"
                      step="any"
                      value={lat}
                      onChange={(e) =>
                        setPolygonPoints((points) =>
                          points.map((p, idx) => (idx === i ? [Number(e.target.value), p[1]] : p)),
                        )
                      }
                      className="w-32 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
                    />
                    <input
                      type="number"
                      step="any"
                      value={lng}
                      onChange={(e) =>
                        setPolygonPoints((points) =>
                          points.map((p, idx) => (idx === i ? [p[0], Number(e.target.value)] : p)),
                        )
                      }
                      className="w-32 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
                    />
                    <button
                      type="button"
                      onClick={() =>
                        setPolygonPoints((points) => points.filter((_, idx) => idx !== i))
                      }
                      className="text-xs text-red-600 underline"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <p className="text-xs text-zinc-500">
            {boundaryType === "circle"
              ? "Click the map, or type coordinates above, to set the center."
              : "Click the map to add points, or type/edit coordinates below."}
          </p>

          <div className="h-[500px] overflow-hidden rounded-lg border border-zinc-200 dark:border-zinc-800">
            <GeofenceMap
              mode={boundaryType}
              center={circleCenter}
              radiusMeters={radiusMeters}
              polygonPoints={polygonPoints}
              onCenterChange={setCircleCenter}
              onPolygonPointAdd={(p) => setPolygonPoints((points) => [...points, p])}
              existingGeofences={geofences}
              focusPoint={focusPoint}
              focusToken={focusToken}
            />
          </div>
        </div>

        {/* Assignment panel */}
        <div className="flex flex-col gap-2 overflow-y-auto rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
          <h2 className="text-sm font-medium text-zinc-500">
            {selectedGeofence ? `Assigned — ${selectedGeofence.name}` : "Select a site"}
          </h2>
          {assignError && <p className="text-sm text-red-600">{assignError}</p>}
          {selectedGeofence && (
            <>
              <ul className="flex flex-col gap-1">
                {assigned.map((e) => (
                  <li
                    key={e.id}
                    className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1 text-sm dark:border-zinc-800"
                  >
                    <span>
                      {e.full_name} ({e.employee_code}){e.job_title && ` — ${e.job_title}`}
                    </span>
                    <button
                      onClick={() => handleUnassign(e.id)}
                      className="text-xs text-red-600 underline"
                    >
                      Remove
                    </button>
                  </li>
                ))}
                {assigned.length === 0 && (
                  <li className="text-sm text-zinc-400">No one assigned yet.</li>
                )}
              </ul>

              <input
                placeholder="Search employees…"
                value={employeeSearch}
                onChange={(e) => setEmployeeSearch(e.target.value)}
                className="mt-3 rounded border border-zinc-300 px-2 py-1 text-sm dark:border-zinc-700 dark:bg-zinc-900"
              />
              <ul className="flex flex-col gap-1">
                {filteredEmployees
                  .filter((e) => !assignedIds.has(e.id))
                  .map((e) => (
                    <li
                      key={e.id}
                      className="flex items-center justify-between rounded border border-zinc-200 px-2 py-1 text-sm dark:border-zinc-800"
                    >
                      <span>
                        {e.employee_code} — {e.user.full_name}
                      </span>
                      <button
                        onClick={() => handleAssign(e.id)}
                        className="text-xs text-blue-600 underline"
                      >
                        Assign
                      </button>
                    </li>
                  ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function GeofencesPage() {
  return (
    <RequireAuth allowedRoles={["hr_manager", "admin", "super_admin"]}>
      <GeofencesPageContent />
    </RequireAuth>
  );
}
