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

  listWorkspaceMembers(workspaceId) {
    return httpClient.get(`/api/v1/workspaces/${workspaceId}/members`);
  },

  addWorkspaceMember(workspaceId, data) {
    return httpClient.post(`/api/v1/workspaces/${workspaceId}/members`, data);
  },

  addProjectMember(projectId, data) {
    return httpClient.post(`/api/v1/projects/${projectId}/members`, data);
  },

  removeProjectMember(projectId, userId) {
    return httpClient.delete(`/api/v1/projects/${projectId}/members/${userId}`);
  },

  getGitHistory(projectId, params = {}) {
    const query = new URLSearchParams();
    if (params.search) query.set('search', params.search);
    if (params.author) query.set('author', params.author);
    if (params.source_id) query.set('source_id', params.source_id);
    if (params.page) query.set('page', params.page);
    if (params.per_page) query.set('per_page', params.per_page);
    const qs = query.toString();
    return httpClient.get(`/api/v1/projects/${projectId}/git-history${qs ? `?${qs}` : ''}`);
  },
};

