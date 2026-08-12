import { api } from "./api";

export interface ProblemReport {
  id: string;
  employee_id: string;
  attendance_id: string | null;
  message: string;
  status: "open" | "resolved";
  created_at: string;
}

export async function createProblemReport(
  message: string,
  attendanceId?: string | null,
): Promise<ProblemReport> {
  const response = await api.post<ProblemReport>("/problem-reports", {
    message,
    attendance_id: attendanceId ?? undefined,
  });
  return response.data;
}
