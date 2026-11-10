/**
 * Dashboard & overview metrics API client.
 * Phase 10 — Hardening & Demo.
 */
import { httpClient } from './httpClient';

export const dashboardApi = {
  getStats(workspaceId = null) {
    const url = workspaceId
      ? `/api/v1/dashboard/stats?workspace_id=${workspaceId}`
      : '/api/v1/dashboard/stats';
    return httpClient.get(url);
  },
};
