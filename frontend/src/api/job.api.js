/**
 * Job progress API methods.
 */
import { httpClient } from './httpClient';

export const jobApi = {
  getJob(jobId) {
    return httpClient.get(`/api/v1/jobs/${jobId}`);
  },
};
