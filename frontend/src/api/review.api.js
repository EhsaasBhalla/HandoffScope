import { httpClient } from './httpClient';

export const reviewApi = {
  getReviewQueue: (caseId) =>
    httpClient.get(`/api/v1/cases/${caseId}/review-queue`),
  reviewClaim: (claimId, data) =>
    httpClient.patch(`/api/v1/claims/${claimId}/review`, data),
  createVersion: (caseId, data = {}) =>
    httpClient.post(`/api/v1/cases/${caseId}/versions`, data),
  listVersions: (caseId) =>
    httpClient.get(`/api/v1/cases/${caseId}/versions`),
  getVersion: (versionId) =>
    httpClient.get(`/api/v1/versions/${versionId}`),
};
