/**
 * Handover case API methods.
 */
import { httpClient } from './httpClient';

export const caseApi = {
  listCases(projectId) {
    return httpClient.get(`/api/v1/projects/${projectId}/cases`);
  },

  createCase(projectId, data) {
    return httpClient.post(`/api/v1/projects/${projectId}/cases`, data);
  },

  getCase(caseId) {
    return httpClient.get(`/api/v1/cases/${caseId}`);
  },

  updateCase(caseId, data) {
    return httpClient.patch(`/api/v1/cases/${caseId}`, data);
  },

  changeStatus(caseId, targetStatus, reason = null) {
    return httpClient.post(`/api/v1/cases/${caseId}/status`, {
      target_status: targetStatus,
      reason,
    });
  },

  addParticipant(caseId, userId, role) {
    return httpClient.post(`/api/v1/cases/${caseId}/participants`, {
      user_id: userId,
      role,
    });
  },

  setBlocked(caseId, blocked, reason = null) {
    return httpClient.patch(`/api/v1/cases/${caseId}/block`, { blocked, reason });
  },
};
