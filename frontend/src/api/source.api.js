/**
 * Source & import API methods.
 */
import { httpClient } from './httpClient';

export const sourceApi = {
  listSources(projectId) {
    return httpClient.get(`/api/v1/projects/${projectId}/sources`);
  },

  connectSource(projectId, data) {
    return httpClient.post(`/api/v1/projects/${projectId}/sources`, data);
  },

  triggerImport(sourceId) {
    return httpClient.post(`/api/v1/sources/${sourceId}/import`);
  },

  listSyncRuns(sourceId) {
    return httpClient.get(`/api/v1/sources/${sourceId}/sync-runs`);
  },

  refreshSource(sourceId, simulateModification = false) {
    return httpClient.post(`/api/v1/sources/${sourceId}/refresh`, {
      simulate_modification: simulateModification,
    });
  },

  refreshCaseSources(caseId, simulateModification = false) {
    return httpClient.post(`/api/v1/cases/${caseId}/refresh-sources`, {
      simulate_modification: simulateModification,
    });
  },
};


export const githubApi = {
  getInstallUrl() {
    return httpClient.get('/api/v1/github/install-url');
  },

  getStatus(workspaceId) {
    return httpClient.get(`/api/v1/github/status?workspace_id=${workspaceId}`);
  },

  disconnect(workspaceId) {
    return httpClient.delete(`/api/v1/github/disconnect?workspace_id=${workspaceId}`);
  },
};
