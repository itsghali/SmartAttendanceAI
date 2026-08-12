import { api } from "./api";

export type ProblemReportStatus = "open" | "resolved";

export interface ProblemReport {
  id: string;
  employee_id: string;
  employee_full_name: string;
  employee_code: string;
  attendance_id: string | null;
  message: string;
  status: ProblemReportStatus;
  created_at: string;
  resolved_at: string | null;
  resolved_by_id: string | null;
}

export interface ProblemReportList {
  items: ProblemReport[];
  total: number;
  limit: number;
  offset: number;
}

export interface ProblemReportListParams {
  status?: ProblemReportStatus;
  limit?: number;
  offset?: number;
}

export async function listProblemReports(
  params: ProblemReportListParams = {},
): Promise<ProblemReportList> {
  const response = await api.get<ProblemReportList>("/problem-reports", {
    params: {
      status: params.status,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    },
  });
  return response.data;
}

export async function resolveProblemReport(id: string): Promise<ProblemReport> {
  const response = await api.patch<ProblemReport>(`/problem-reports/${id}/resolve`);
  return response.data;
}
