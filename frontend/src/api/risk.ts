import { apiClient } from "./client";
import type {
  AlertResponse,
  AtRiskStudentResponse,
  InterventionCreateRequest,
  InterventionOutcomeCreateRequest,
  InterventionOutcomeResponse,
  InterventionResponse,
  InterventionUpdateRequest,
  RecomputeRequest,
  RecomputeSummaryResponse,
  RiskConfigResponse,
  RiskConfigUpdateRequest,
  RiskSummaryByDepartmentResponse,
  RiskSummaryResponse,
  StudentRiskDetailResponse,
} from "./types";

export interface AtRiskStudentFilters {
  tier?: string;
  risk_type?: string;
  department?: string;
  min_score?: number;
  page?: number;
}

export async function listAtRiskStudents(filters: AtRiskStudentFilters): Promise<AtRiskStudentResponse[]> {
  const { data } = await apiClient.get<AtRiskStudentResponse[]>("/risk/students", { params: filters });
  return data;
}

export async function getStudentRisk(studentId: string): Promise<StudentRiskDetailResponse> {
  const { data } = await apiClient.get<StudentRiskDetailResponse>(`/risk/students/${studentId}`);
  return data;
}

export async function getRiskSummary(): Promise<RiskSummaryResponse> {
  const { data } = await apiClient.get<RiskSummaryResponse>("/risk/summary");
  return data;
}

export async function getRiskSummaryByDepartment(): Promise<RiskSummaryByDepartmentResponse> {
  const { data } = await apiClient.get<RiskSummaryByDepartmentResponse>("/risk/summary/by-department");
  return data;
}

export async function createIntervention(payload: InterventionCreateRequest): Promise<InterventionResponse> {
  const { data } = await apiClient.post<InterventionResponse>("/risk/interventions", payload);
  return data;
}

export async function listInterventions(studentId: string): Promise<InterventionResponse[]> {
  const { data } = await apiClient.get<InterventionResponse[]>("/risk/interventions", {
    params: { student_id: studentId },
  });
  return data;
}

export async function updateIntervention(
  interventionId: string,
  payload: InterventionUpdateRequest,
): Promise<InterventionResponse> {
  const { data } = await apiClient.patch<InterventionResponse>(`/risk/interventions/${interventionId}`, payload);
  return data;
}

export async function recordOutcome(
  interventionId: string,
  payload: InterventionOutcomeCreateRequest,
): Promise<InterventionOutcomeResponse> {
  const { data } = await apiClient.post<InterventionOutcomeResponse>(
    `/risk/interventions/${interventionId}/outcome`,
    payload,
  );
  return data;
}

export async function listAlerts(status?: string): Promise<AlertResponse[]> {
  const { data } = await apiClient.get<AlertResponse[]>("/risk/alerts", { params: status ? { status } : {} });
  return data;
}

export async function markAlertRead(alertId: string): Promise<AlertResponse> {
  const { data } = await apiClient.patch<AlertResponse>(`/risk/alerts/${alertId}/read`);
  return data;
}

export async function getRiskConfig(): Promise<RiskConfigResponse> {
  const { data } = await apiClient.get<RiskConfigResponse>("/risk/config");
  return data;
}

export async function updateRiskConfig(payload: RiskConfigUpdateRequest): Promise<RiskConfigResponse> {
  const { data } = await apiClient.put<RiskConfigResponse>("/risk/config", payload);
  return data;
}

export async function recompute(payload: RecomputeRequest): Promise<RecomputeSummaryResponse> {
  const { data } = await apiClient.post<RecomputeSummaryResponse>("/risk/recompute", payload);
  return data;
}
