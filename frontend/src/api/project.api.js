/**
 * Project & workspace API methods.
 */
import { httpClient } from './httpClient';

export const projectApi = {
  listWorkspaces() {
    return httpClient.get('/api/v1/workspaces');
  },

  getWorkspace(workspaceId) {
    return httpClient.get(`/api/v1/workspaces/${workspaceId}`);
  },

  listProjects(workspaceId) {
    return httpClient.get(`/api/v1/workspaces/${workspaceId}/projects`);
  },

  createProject(workspaceId, data) {
    return httpClient.post(`/api/v1/workspaces/${workspaceId}/projects`, data);
  },

  getProject(projectId) {
    return httpClient.get(`/api/v1/projects/${projectId}`);
  },

  listProjectMembers(projectId) {
    return httpClient.get(`/api/v1/projects/${projectId}/members`);
  },
};
