import { httpClient } from './httpClient';

export const questionApi = {
  listQuestions: (params = {}) => {
    const query = new URLSearchParams(params).toString();
    const url = query ? `/api/v1/questions?${query}` : '/api/v1/questions';
    return httpClient.get(url);
  },
  listCaseQuestions: (caseId, params = {}) => {
    const query = new URLSearchParams(params).toString();
    const url = query ? `/api/v1/cases/${caseId}/questions?${query}` : `/api/v1/cases/${caseId}/questions`;
    return httpClient.get(url);
  },
  getQuestion: (questionId) =>
    httpClient.get(`/api/v1/questions/${questionId}`),
  createQuestion: (caseId, data) =>
    httpClient.post(`/api/v1/cases/${caseId}/questions`, data),
  updateQuestion: (questionId, data) =>
    httpClient.patch(`/api/v1/questions/${questionId}`, data),
  submitResponse: (questionId, data) =>
    httpClient.post(`/api/v1/questions/${questionId}/responses`, data),
  generateAiAnswer: (questionId) =>
    httpClient.post(`/api/v1/questions/${questionId}/generate-answer`),
  reviewResponse: (questionId, data) =>
    httpClient.patch(`/api/v1/questions/${questionId}/review`, data),
};
