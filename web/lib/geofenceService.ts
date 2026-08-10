import { api } from "./api";

export type BoundaryType = "circle" | "polygon";

export interface PolygonPoint {
  latitude: number;
  longitude: number;
}

export interface Geofence {
  id: string;
  name: string;
  department_id: string | null;
  boundary_type: BoundaryType;
  center_latitude: number | null;
  center_longitude: number | null;
  radius_meters: number | null;
  polygon_points: PolygonPoint[] | null;
  is_active: boolean;
}

export interface GeofenceCreateInput {
  name: string;
  department_id?: string | null;
  boundary_type: BoundaryType;
  center_latitude?: number | null;
  center_longitude?: number | null;
  radius_meters?: number | null;
  polygon_points?: PolygonPoint[] | null;
}

export interface AssignedEmployee {
  id: string;
  employee_code: string;
  full_name: string;
  job_title: string;
}

export async function listGeofences(): Promise<Geofence[]> {
  const response = await api.get("/geofences", { params: { limit: 200 } });
  return response.data.items;
}

export async function createGeofence(input: GeofenceCreateInput): Promise<Geofence> {
  const response = await api.post("/geofences", input);
  return response.data;
}

export interface GeofenceUpdateInput {
  name: string;
  department_id: string | null;
  boundary_type: BoundaryType;
  center_latitude: number | null;
  center_longitude: number | null;
  radius_meters: number | null;
  polygon_points: PolygonPoint[] | null;
}

export async function updateGeofence(id: string, input: GeofenceUpdateInput): Promise<Geofence> {
  const response = await api.patch(`/geofences/${id}`, input);
  return response.data;
}

export async function setGeofenceActive(id: string, isActive: boolean): Promise<void> {
  await api.patch(`/geofences/${id}`, { is_active: isActive });
}

export async function listAssignedEmployees(geofenceId: string): Promise<AssignedEmployee[]> {
  const response = await api.get(`/geofences/${geofenceId}/employees`);
  return response.data.items;
}

export async function assignEmployee(geofenceId: string, employeeId: string): Promise<void> {
  await api.post(`/geofences/${geofenceId}/employees/${employeeId}`);
}

export async function unassignEmployee(geofenceId: string, employeeId: string): Promise<void> {
  await api.delete(`/geofences/${geofenceId}/employees/${employeeId}`);
}
