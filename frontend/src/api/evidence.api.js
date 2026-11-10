import { httpClient } from './httpClient';

export const evidenceApi = {
  triggerReconstruction: (caseId) =>
    httpClient.post(`/api/v1/cases/${caseId}/reconstruct`),
  listExtractionRuns: (caseId) =>
    httpClient.get(`/api/v1/cases/${caseId}/extraction-runs`),
  getExtractionRun: (runId) =>
    httpClient.get(`/api/v1/extraction-runs/${runId}`),
  listClaimsForPack: (packId, params = {}) => {
    const query = new URLSearchParams(
      Object.entries(params).filter(([_, v]) => v !== undefined && v !== null && v !== '')
    ).toString();
    const url = query
      ? `/api/v1/transfer-packs/${packId}/claims?${query}`
      : `/api/v1/transfer-packs/${packId}/claims`;
    return httpClient.get(url);
  },
  getClaim: (claimId) =>
    httpClient.get(`/api/v1/claims/${claimId}`),
  getClaimEvidence: (claimId) =>
    httpClient.get(`/api/v1/claims/${claimId}/evidence`),
  updateClaim: (claimId, data) =>
    httpClient.patch(`/api/v1/claims/${claimId}`, data),
};
