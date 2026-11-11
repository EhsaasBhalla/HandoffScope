/**
 * Auth API methods.
 */

import { clearAuthTokens, httpClient, setAuthTokens, setCsrfToken } from './httpClient';

export const authApi = {
  async login(email, password) {
    const data = await httpClient.post('/api/v1/auth/login', { email, password });
    if (data.csrf_token) {
      setCsrfToken(data.csrf_token);
    }
    if (data.access_token || data.refresh_token) {
      setAuthTokens({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      });
    }
    return data;
  },

  async logout() {
    try {
      return await httpClient.post('/api/v1/auth/logout');
    } finally {
      clearAuthTokens();
    }
  },

  async me() {
    return httpClient.get('/api/v1/auth/me');
  },

  async refresh() {
    const data = await httpClient.post('/api/v1/auth/refresh');
    if (data.csrf_token) {
      setCsrfToken(data.csrf_token);
    }
    if (data.access_token) {
      setAuthTokens({ accessToken: data.access_token });
    }
    return data;
  },
};
