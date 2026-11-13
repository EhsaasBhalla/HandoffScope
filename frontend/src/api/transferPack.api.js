import { httpClient } from './httpClient';

export const transferPackApi = {
  listPacks: (caseId) =>
    httpClient.get(`/api/v1/cases/${caseId}/transfer-packs`),
  getPack: (packId) =>
    httpClient.get(`/api/v1/transfer-packs/${packId}`),
  createPack: (caseId, data) =>
    httpClient.post(`/api/v1/cases/${caseId}/transfer-packs`, data),
  updatePack: (packId, data) =>
    httpClient.patch(`/api/v1/transfer-packs/${packId}`, data),
  moveClaims: (packId, claimIds) =>
    httpClient.post(`/api/v1/transfer-packs/${packId}/claims`, {
      claim_ids: Array.isArray(claimIds) ? claimIds : (claimIds ? [claimIds] : []),
    }),
  mergePacks: (packId, sourcePackId) =>
    httpClient.post(`/api/v1/transfer-packs/${packId}/merge`, {
      source_pack_id: sourcePackId,
    }),
  splitPack: (packId, data) =>
    httpClient.post(`/api/v1/transfer-packs/${packId}/split`, data),
  transitionStatus: (packId, status) =>
    httpClient.post(`/api/v1/transfer-packs/${packId}/status`, { status }),
};
