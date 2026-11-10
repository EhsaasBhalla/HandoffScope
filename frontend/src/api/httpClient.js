/**
 * HTTP client wrapper with credentials and CSRF support.
 *
 * All requests include credentials (cookies) and the X-CSRF-Token header.
 */

const rawBase = import.meta.env.VITE_API_URL || '';
const BASE_URL = rawBase.endsWith('/') ? rawBase.slice(0, -1) : rawBase;

let csrfToken = null;

export function setCsrfToken(token) {
  csrfToken = token;
}

async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };

  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }

  const config = {
    ...options,
    headers,
    credentials: 'include',
  };

  const response = await fetch(url, config);

  // Extract CSRF token from response header if present
  const newCsrf = response.headers.get('X-CSRF-Token');
  if (newCsrf) {
    csrfToken = newCsrf;
  }

  if (response.status === 204) {
    return null;
  }

  const data = await response.json();

  if (!response.ok) {
    const error = new Error(data?.error?.message || `Request failed: ${response.status}`);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

export const httpClient = {
  get:    (url, opts) => request(url, { ...opts, method: 'GET' }),
  post:   (url, body, opts) => request(url, { ...opts, method: 'POST', body: JSON.stringify(body) }),
  put:    (url, body, opts) => request(url, { ...opts, method: 'PUT', body: JSON.stringify(body) }),
  patch:  (url, body, opts) => request(url, { ...opts, method: 'PATCH', body: JSON.stringify(body) }),
  delete: (url, opts) => request(url, { ...opts, method: 'DELETE' }),

  // For file uploads — no JSON content type
  upload: (url, formData, opts) => request(url, {
    ...opts,
    method: 'POST',
    body: formData,
    headers: {}, // Let browser set Content-Type with boundary
  }),
};
