import { httpClient } from './httpClient';

export const timelineApi = {
  getTimeline: (projectId, params = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([_, v]) => v !== undefined && v !== null && v !== '')
    ).toString();
    const url = query
      ? `/api/v1/projects/${projectId}/timeline?${query}`
      : `/api/v1/projects/${projectId}/timeline`;
    return httpClient.get(url);
  },
};
