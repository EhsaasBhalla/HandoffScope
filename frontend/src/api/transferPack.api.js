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
};
