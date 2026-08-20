import { api } from "./api";
import { DeviationSeverity, InsightEvidence, RecommendedAction } from "./workforceIntelligenceService";

export interface AppNotification {
  id: string;
  employee_id: string;
  deviation_flag_id: string | null;
  metric: string;
  severity: DeviationSeverity;
  title: string;
  summary: string;
  evidence: InsightEvidence;
  recommended_action: RecommendedAction[];
  occurred_at: string;
  detected_at: string;
  is_read: boolean;
  read_at: string | null;
  email_status: string;
  created_at: string;
}

export interface NotificationList {
  items: AppNotification[];
  total: number;
  limit: number;
  offset: number;
}

export interface ListNotificationsParams {
  unread_only?: boolean;
  limit?: number;
  offset?: number;
}

export async function listNotifications(
  params: ListNotificationsParams = {},
): Promise<NotificationList> {
  const response = await api.get<NotificationList>("/notifications", {
    params: {
      unread_only: params.unread_only,
      limit: params.limit ?? 20,
      offset: params.offset ?? 0,
    },
  });
  return response.data;
}

export async function getUnreadNotificationCount(): Promise<number> {
  const response = await api.get<{ unread_count: number }>("/notifications/unread-count");
  return response.data.unread_count;
}

export async function markNotificationRead(id: string): Promise<AppNotification> {
  const response = await api.patch<AppNotification>(`/notifications/${id}/read`);
  return response.data;
}
