/**
 * Conversational RAG ("Ask the Handover") API client methods.
 */
import { httpClient } from './httpClient';

export const ragApi = {
  listThreads(caseId) {
    return httpClient.get(`/api/v1/cases/${caseId}/chat/threads`);
  },

  getThread(caseId, threadId) {
    return httpClient.get(`/api/v1/cases/${caseId}/chat/threads/${threadId}`);
  },

  askQuestion(caseId, data) {
    return httpClient.post(`/api/v1/cases/${caseId}/chat/ask`, data);
  },

  reindex(caseId, data = {}) {
    return httpClient.post(`/api/v1/cases/${caseId}/chat/reindex`, data);
  },
};
