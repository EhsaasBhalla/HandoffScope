import { httpClient } from './httpClient';

export const sharingApi = {
  shareVersion: (versionId, recipientUserId) =>
    httpClient.post(`/api/v1/versions/${versionId}/share`, {
      recipient_user_id: recipientUserId,
    }),
  listVersionShares: (versionId) =>
    httpClient.get(`/api/v1/versions/${versionId}/shares`),
  listCaseShares: (caseId) =>
    httpClient.get(`/api/v1/cases/${caseId}/shares`),
  revokeShare: (grantId) =>
    httpClient.delete(`/api/v1/share-grants/${grantId}`),
};
