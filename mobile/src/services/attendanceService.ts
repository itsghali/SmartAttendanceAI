import { api } from "./api";

export type AttendanceStatus = "present" | "late" | "remote";
export type GeofenceEventType = "enter" | "exit" | "return";
// "no_active_checkin" | "not_monitored" | "geofence_removed" | "on_break" | "in_zone" | "exited"
export type PingStatus = string;

export interface BreakPeriod {
  id: string;
  break_start_at: string;
  break_end_at: string | null;
  start_latitude: number | null;
  start_longitude: number | null;
  start_accuracy_meters: number | null;
  end_latitude: number | null;
  end_longitude: number | null;
  end_accuracy_meters: number | null;
}

export interface GeofenceEvent {
  id: string;
  event_type: GeofenceEventType;
  latitude: number;
  longitude: number;
  created_at: string;
}

export interface Attendance {
  id: string;
  employee_id: string;
  attendance_date: string;
  check_in_at: string;
  check_in_latitude: number | null;
  check_in_longitude: number | null;
  check_in_accuracy_meters: number | null;
  check_in_geofence_id: string | null;
  check_out_at: string | null;
  check_out_latitude: number | null;
  check_out_longitude: number | null;
  check_out_accuracy_meters: number | null;
  check_out_geofence_id: string | null;
  status: AttendanceStatus;
  is_manual_entry: boolean;
  notes: string;
  breaks: BreakPeriod[];
  geofence_events: GeofenceEvent[];
  // "not_monitored" | "on_break" | "live" | "stale" | null (session closed).
  monitoring_status: string | null;
}

/**
 * An employee's day, which may span several chantiers.
 *
 * `current` is the session open right now — null when they are checked out of
 * everything — and is what the screen drives its buttons off. `sessions` is
 * every session that started today, including the finished ones.
 */
export interface TodayAttendance {
  current: Attendance | null;
  sessions: Attendance[];
}

interface CheckInPayload {
  latitude: number;
  longitude: number;
  accuracy_meters?: number | null;
  // Base64-encoded selfie JPEG. Required by every one of check-in,
  // check-out, break/start, break/end when the server has
  // FACE_VERIFICATION_ENABLED on; a harmless no-op field otherwise.
  selfie_base64?: string;
  // Only enforced by the backend on check-in (see PLAN.md T1) — a harmless
  // unused field on the other three actions, kept on the shared payload
  // shape rather than a second interface for one field.
  is_mock_location?: boolean;
  // Only used by the backend on check-in — a JS-level heuristic (iOS only,
  // see deviceIntegrityService.ts), weaker than is_mock_location, so it
  // flags the row for HR review server-side rather than blocking.
  is_jailbroken?: boolean;
}

interface LocationPingPayload {
  latitude: number;
  longitude: number;
  accuracy_meters?: number | null;
  ping_seq: number;
}

export interface LocationPingResult {
  status: PingStatus;
  event_fired: GeofenceEventType | null;
  next_seq: number | null;
}

export async function checkIn(payload: CheckInPayload): Promise<Attendance> {
  const response = await api.post<Attendance>("/attendance/check-in", payload);
  return response.data;
}

export async function checkOut(payload: CheckInPayload): Promise<Attendance> {
  const response = await api.post<Attendance>("/attendance/check-out", payload);
  return response.data;
}

export async function startBreak(payload: CheckInPayload): Promise<BreakPeriod> {
  const response = await api.post<BreakPeriod>("/attendance/break/start", payload);
  return response.data;
}

export async function endBreak(payload: CheckInPayload): Promise<BreakPeriod> {
  const response = await api.post<BreakPeriod>("/attendance/break/end", payload);
  return response.data;
}

export async function getTodayAttendance(): Promise<TodayAttendance> {
  const response = await api.get<TodayAttendance>("/attendance/me/today");
  return response.data;
}

export async function sendLocationPing(payload: LocationPingPayload): Promise<LocationPingResult> {
  const response = await api.post<LocationPingResult>("/attendance/location-ping", payload);
  return response.data;
}
