import { httpClient } from './httpClient';

export const recipientApi = {
  listMySuccessorCases: () =>
    httpClient.get('/api/v1/recipient/cases'),
  getSuccessorView: (caseId) =>
    httpClient.get(`/api/v1/recipient/cases/${caseId}`),
  acknowledgeCase: (caseId) =>
    httpClient.post(`/api/v1/recipient/cases/${caseId}/acknowledge`),
  listResponsibilities: (caseId) =>
    httpClient.get(`/api/v1/cases/${caseId}/responsibilities`),
  assignResponsibility: (caseId, data) =>
    httpClient.post(`/api/v1/cases/${caseId}/responsibilities`, data),
  acceptResponsibility: (assignmentId) =>
    httpClient.post(`/api/v1/responsibility-assignments/${assignmentId}/accept`),
  declineResponsibility: (assignmentId, reason) =>
    httpClient.post(`/api/v1/responsibility-assignments/${assignmentId}/decline`, {
      reason,
    }),
  delegateClaim: (claimId, data) =>
    httpClient.post(`/api/v1/recipients/claims/${claimId}/delegate`, data),
  revokeDelegation: (assignmentId) =>
    httpClient.post(`/api/v1/responsibility-assignments/${assignmentId}/revoke`),
};
