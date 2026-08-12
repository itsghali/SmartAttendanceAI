import { api } from "./api";

export type AttendanceStatus = "present" | "late" | "remote";

export interface Attendance {
  id: string;
  employee_id: string;
  attendance_date: string;
  check_in_at: string;
  check_out_at: string | null;
  status: AttendanceStatus;
  is_manual_entry: boolean;
  notes: string;
  // "not_monitored" | "on_break" | "live" | "stale" | null (session closed)
  monitoring_status: string | null;
}

export interface AttendanceList {
  items: Attendance[];
  total: number;
  limit: number;
  offset: number;
}

export interface AttendanceListParams {
  dateFrom?: string;
  dateTo?: string;
  limit?: number;
  offset?: number;
}

// GET /attendance — auto-scoped server-side to the caller's own department
// when the caller is a supervisor (see backend attendance.list_all_attendance);
// no department_id param needed here for that role.
export async function listAttendance(params: AttendanceListParams = {}): Promise<AttendanceList> {
  const response = await api.get("/attendance", {
    params: {
      date_from: params.dateFrom || undefined,
      date_to: params.dateTo || undefined,
      limit: params.limit ?? 100,
      offset: params.offset ?? 0,
    },
  });
  return response.data;
}

export interface AttendanceCorrection {
  check_in_at?: string;
  check_out_at?: string | null;
  status?: AttendanceStatus;
  notes?: string;
}

export async function correctAttendance(
  id: string,
  correction: AttendanceCorrection,
): Promise<Attendance> {
  const response = await api.patch(`/attendance/${id}`, correction);
  return response.data;
}
