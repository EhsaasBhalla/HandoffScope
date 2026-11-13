/**
 * Compliance archival export & cryptographic verification API methods.
 */
import { httpClient } from './httpClient';

export const exportApi = {
  getSigningKey() {
    return httpClient.get('/api/v1/exports/signing-key');
  },

  downloadCertificatePdf(caseId, versionNumber) {
    const query = versionNumber ? `?version_number=${versionNumber}` : '';
    const suffix = versionNumber ? `-v${versionNumber}` : '';
    return httpClient.download(
      `/api/v1/cases/${caseId}/exports/certificate.pdf${query}`,
      `handoff-certificate${suffix}.pdf`
    );
  },

  downloadComplianceBundle(caseId, versionNumber) {
    const query = versionNumber ? `?version_number=${versionNumber}` : '';
    const suffix = versionNumber ? `-v${versionNumber}` : '';
    return httpClient.download(
      `/api/v1/cases/${caseId}/exports/compliance-bundle.zip${query}`,
      `handoff-compliance-bundle${suffix}.zip`
    );
  },

  verifyBundle(file) {
    const formData = new FormData();
    formData.append('file', file);
    return httpClient.upload('/api/v1/exports/verify', formData);
  },
};
