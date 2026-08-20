import { api } from "./api";

export type SyntheticDataRunStatus = "requested" | "running" | "completed" | "failed";

export interface SyntheticDataRun {
  id: string;
  status: SyntheticDataRunStatus;
  employee_scope: string[];
  date_range_start: string;
  date_range_end: string;
  anomaly_config: Record<string, unknown>;
  error_message: string | null;
  row_counts: Record<string, unknown> | null;
  idempotency_key: string | null;
  created_at: string;
}

export interface GenerateSyntheticDataPayload {
  employee_ids: string[];
  date_range_start: string;
  date_range_end: string;
  anomaly_config?: Record<string, unknown>;
  seed: number;
  idempotency_key?: string;
}

export async function generateSyntheticData(
  payload: GenerateSyntheticDataPayload,
): Promise<SyntheticDataRun> {
  const response = await api.post("/workforce-intelligence/synthetic-data/generate", payload);
  return response.data;
}

export async function getSyntheticRun(runId: string): Promise<SyntheticDataRun> {
  const response = await api.get(`/workforce-intelligence/synthetic-data/${runId}`);
  return response.data;
}

export interface MetricStats {
  mean: number | null;
  std: number | null;
  n: number;
}

export interface PeerMetricStats extends MetricStats {
  source: "department" | "company_wide";
  department_id: string | null;
}

export interface MetricStatsEntry {
  self: MetricStats;
  peer: PeerMetricStats;
}

export interface EmployeeBaseline {
  employee_id: string;
  window_start: string;
  window_end: string;
  metric_stats: Record<string, MetricStatsEntry>;
  computed_at: string;
}

export interface RebuildBaselinesPayload {
  employee_ids: string[];
  window_start: string;
  window_end: string;
}

export interface RebuildBaselinesResult {
  built: string[];
  skipped_insufficient_history: string[];
  skipped_terminated: string[];
}

export async function rebuildBaselines(
  payload: RebuildBaselinesPayload,
): Promise<RebuildBaselinesResult> {
  const response = await api.post("/workforce-intelligence/baselines/rebuild", payload);
  return response.data;
}

export async function getBaseline(employeeId: string): Promise<EmployeeBaseline | null> {
  try {
    const response = await api.get(`/workforce-intelligence/baselines/${employeeId}`);
    return response.data;
  } catch (err) {
    if (isNotFound(err)) return null;
    throw err;
  }
}

export interface RunDetectionPayload {
  employee_ids: string[];
  window_start: string;
  window_end: string;
}

export interface RunDetectionResult {
  scored: string[];
  skipped_no_baseline: string[];
  flag_counts: Record<string, number>;
}

export async function runDetection(payload: RunDetectionPayload): Promise<RunDetectionResult> {
  const response = await api.post("/workforce-intelligence/detection/run", payload);
  return response.data;
}

export type DeviationSeverity = "moderate" | "high";
export type ReviewStatus = "new" | "reviewed" | "dismissed";

export interface EmployeeDeviationFlag {
  id: string;
  employee_id: string;
  attendance_id: string;
  metric: string;
  occurred_at: string;
  observed_value: number;
  self_mean: number;
  self_std: number;
  self_z: number | null;
  self_n: number | null;
  peer_mean: number;
  peer_std: number;
  peer_z: number | null;
  peer_n: number | null;
  severity: DeviationSeverity;
  window_start: string;
  window_end: string;
  detected_at: string;
  is_synthetic: boolean;
  synthetic_anomaly_type: string | null;
  review_status: ReviewStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
}

export interface ListDeviationFlagsParams {
  employee_id?: string;
  window_start?: string;
  window_end?: string;
  limit?: number;
  offset?: number;
}

export interface DeviationFlagList {
  items: EmployeeDeviationFlag[];
  total: number;
  limit: number;
  offset: number;
}

export async function listDeviationFlags(
  params: ListDeviationFlagsParams = {},
): Promise<DeviationFlagList> {
  const response = await api.get("/workforce-intelligence/detection/flags", { params });
  return response.data;
}

export interface ImpossibleTravelRejection {
  id: string;
  employee_id: string;
  prior_attendance_id: string | null;
  attempted_at: string;
  distance_km: number;
  elapsed_hours: number;
  implied_speed_kmh: number;
  risk_score: number;
  created_at: string;
}

export interface ListImpossibleTravelRejectionsParams {
  employee_id?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface ImpossibleTravelRejectionList {
  items: ImpossibleTravelRejection[];
  total: number;
  limit: number;
  offset: number;
}

export async function listImpossibleTravelRejections(
  params: ListImpossibleTravelRejectionsParams = {},
): Promise<ImpossibleTravelRejectionList> {
  const response = await api.get("/workforce-intelligence/impossible-travel-rejections", {
    params,
  });
  return response.data;
}

export interface InsightEvidence {
  current: string;
  baseline: string;
  difference: string;
  historical_observations: number | null;
  severity: DeviationSeverity;
  detection_type: string;
}

export interface InsightTechnical {
  metric: string;
  self_mean: number;
  self_std: number;
  self_z: number | null;
  self_n: number | null;
  peer_mean: number;
  peer_std: number;
  peer_z: number | null;
  peer_n: number | null;
}

export interface RecommendedAction {
  label: string;
  action: string;
}

// Requirement 2's human-readable presentation — title/summary/explanation/
// evidence are the primary view (no metric identifiers or z-scores);
// `technical` carries the same raw statistics for a "Technical Details"
// disclosure only.
export interface WorkforceInsight extends EmployeeDeviationFlag {
  title: string;
  summary: string;
  explanation: string;
  evidence: InsightEvidence;
  technical: InsightTechnical;
  recommended_action: RecommendedAction[];
}

export interface ListInsightsParams {
  employee_id?: string;
  window_start?: string;
  window_end?: string;
  review_status?: ReviewStatus;
  limit?: number;
  offset?: number;
}

export interface InsightList {
  items: WorkforceInsight[];
  total: number;
  limit: number;
  offset: number;
}

export async function listInsights(params: ListInsightsParams = {}): Promise<InsightList> {
  const response = await api.get("/workforce-intelligence/insights", { params });
  return response.data;
}

export async function reviewFlag(
  flagId: string,
  status: ReviewStatus,
): Promise<EmployeeDeviationFlag> {
  const response = await api.patch(`/workforce-intelligence/detection/flags/${flagId}/review`, {
    status,
  });
  return response.data;
}

function isNotFound(err: unknown): boolean {
  return (
    typeof err === "object" &&
    err !== null &&
    "response" in err &&
    (err as { response?: { status?: number } }).response?.status === 404
  );
}
