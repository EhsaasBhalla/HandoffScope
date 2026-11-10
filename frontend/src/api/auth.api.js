/**
 * Auth API methods.
 */

import { httpClient, setCsrfToken } from './httpClient';

export const authApi = {
  async login(email, password) {
    const data = await httpClient.post('/api/v1/auth/login', { email, password });
    if (data.csrf_token) {
      setCsrfToken(data.csrf_token);
    }
    return data;
  },

  async logout() {
    return httpClient.post('/api/v1/auth/logout');
  },

  async me() {
    return httpClient.get('/api/v1/auth/me');
  },

  async refresh() {
    const data = await httpClient.post('/api/v1/auth/refresh');
    if (data.csrf_token) {
      setCsrfToken(data.csrf_token);
    }
    return data;
  },
};
