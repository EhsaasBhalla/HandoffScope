import { httpClient } from './httpClient';

export const identityApi = {
  getMappings: (projectId, params = {}) => {
    const query = new URLSearchParams(params).toString();
    const url = query
      ? `/api/v1/projects/${projectId}/identity-mappings?${query}`
      : `/api/v1/projects/${projectId}/identity-mappings`;
    return httpClient.get(url);
  },
  autoSuggest: (projectId) =>
    httpClient.post(`/api/v1/projects/${projectId}/identity-mappings/auto-suggest`),
  getCoverage: (projectId) =>
    httpClient.get(`/api/v1/projects/${projectId}/identity-coverage`),
  updateMapping: (mappingId, data) =>
    httpClient.patch(`/api/v1/identity-mappings/${mappingId}`, data),
  createMapping: (projectId, data) =>
    httpClient.post(`/api/v1/projects/${projectId}/identity-mappings`, data),
};
