import { api } from "./api";

export type MonitoringStatus = "not_monitored" | "on_break" | "live" | "stale" | null;

export interface AttendanceException {
  employee_id: string;
  employee_full_name: string;
  employee_code: string;
  attendance_id: string;
  check_in_at: string;
  monitoring_status: MonitoringStatus;
  needs_attention: boolean;
}

export interface AttendanceExceptionsList {
  items: AttendanceException[];
  needs_attention_count: number;
  total: number;
}

export type GeofenceEventType = "enter" | "exit" | "return";

// Widened beyond GeofenceEventType — the backend merges check-in/check-out
// into this same timeline (see get_employee_geofence_history), since HR
// resolving a payroll dispute needs the actual session boundary, not just
// the geofence transitions inside it. The event_type filter param on
// getEmployeeGeofenceHistory still only accepts GeofenceEventType — check_in
// /check_out aren't real geofence_events rows, so they can't be filtered by
// that param (see the backend route's own "merge is skipped when event_type
// is set" comment).
export type TimelineEntryType = GeofenceEventType | "check_in" | "check_out";

export interface GeofenceEventSummary {
  id: string;
  event_type: TimelineEntryType;
  // "Deleted geofence" when the source geofence was removed after the
  // event fired, "Not monitored" when there was never one — never blank,
  // the backend always fills this in.
  geofence_name: string;
  created_at: string;
}

export interface GeofenceEventHistory {
  items: GeofenceEventSummary[];
  total: number;
  limit: number;
  offset: number;
}

export async function listAttendanceExceptions(): Promise<AttendanceExceptionsList> {
  const response = await api.get("/attendance/exceptions");
  return response.data;
}

export interface GeofenceHistoryParams {
  dateFrom?: string;
  dateTo?: string;
  eventType?: GeofenceEventType;
  limit?: number;
  offset?: number;
}

const DEFAULT_HISTORY_PAGE_SIZE = 50;

export async function getEmployeeGeofenceHistory(
  employeeId: string,
  params: GeofenceHistoryParams = {},
): Promise<GeofenceEventHistory> {
  const response = await api.get(`/attendance/${employeeId}/history`, {
    params: {
      date_from: params.dateFrom || undefined,
      date_to: params.dateTo || undefined,
      event_type: params.eventType || undefined,
      limit: params.limit ?? DEFAULT_HISTORY_PAGE_SIZE,
      offset: params.offset ?? 0,
    },
  });
  return response.data;
}

export interface FaceVerificationAttempt {
  id: string;
  passed: boolean;
  // "no_face" | "multiple_faces" | "invalid_image" | "not_enrolled" |
  // "low_similarity" | "liveness_failed" | "model_unavailable" |
  // "profile_corrupted" | null (null only when passed is true)
  failure_reason: string | null;
  created_at: string;
}

export interface FaceVerificationAttemptList {
  items: FaceVerificationAttempt[];
  total: number;
  limit: number;
  offset: number;
}

export interface FaceAttemptsParams {
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
}

export async function getEmployeeFaceAttempts(
  employeeId: string,
  params: FaceAttemptsParams = {},
): Promise<FaceVerificationAttemptList> {
  const response = await api.get(`/face/attempts/${employeeId}`, {
    params: {
      date_from: params.dateFrom || undefined,
      date_to: params.dateTo || undefined,
      limit: params.limit ?? DEFAULT_HISTORY_PAGE_SIZE,
      offset: params.offset ?? 0,
    },
  });
  return response.data;
}
