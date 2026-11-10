/**
 * Document upload API methods.
 */
import { httpClient } from './httpClient';

export const documentApi = {
  listDocuments(projectId) {
    return httpClient.get(`/api/v1/projects/${projectId}/documents`);
  },

  uploadDocument(projectId, file) {
    const formData = new FormData();
    formData.append('file', file);
    return httpClient.upload(`/api/v1/projects/${projectId}/documents`, formData);
  },

  getDocument(documentId) {
    return httpClient.get(`/api/v1/documents/${documentId}`);
  },
};
