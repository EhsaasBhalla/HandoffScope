/**
 * HTTP client wrapper with cookie + Bearer auth fallback, automatic 401 refresh, and CSRF support.
 */

const rawBase = import.meta.env.VITE_API_URL || '';
const BASE_URL = rawBase.endsWith('/') ? rawBase.slice(0, -1) : rawBase;

const ACCESS_KEY = 'hs_access_token';
const REFRESH_KEY = 'hs_refresh_token';

let csrfToken = null;
let refreshPromise = null;

function readStorage(key) {
  try {
    return window.localStorage.getItem(key) || null;
  } catch {
    return null;
  }
}

function writeStorage(key, val) {
  try {
    if (val) {
      window.localStorage.setItem(key, val);
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    // Ignore storage quota / privacy mode errors
  }
}

export function setCsrfToken(token) {
  csrfToken = token;
}

export function setAuthTokens({ accessToken, refreshToken } = {}) {
  if (accessToken !== undefined) writeStorage(ACCESS_KEY, accessToken);
  if (refreshToken !== undefined) writeStorage(REFRESH_KEY, refreshToken);
}

export function clearAuthTokens() {
  csrfToken = null;
  writeStorage(ACCESS_KEY, null);
  writeStorage(REFRESH_KEY, null);
}

async function performTokenRefresh() {
  if (refreshPromise) {
    return refreshPromise;
  }
  refreshPromise = (async () => {
    try {
      const storedRefresh = readStorage(REFRESH_KEY);
      const headers = { 'Content-Type': 'application/json' };
      if (csrfToken) headers['X-CSRF-Token'] = csrfToken;

      const res = await fetch(`${BASE_URL}/api/v1/auth/refresh`, {
        method: 'POST',
        headers,
        credentials: 'include',
        body: storedRefresh ? JSON.stringify({ refresh_token: storedRefresh }) : undefined,
      });

      if (!res.ok) {
        clearAuthTokens();
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('handoffscope:auth-expired'));
        }
        return false;
      }

      const data = await res.json().catch(() => null);
      if (data?.csrf_token) setCsrfToken(data.csrf_token);
      if (data?.access_token) setAuthTokens({ accessToken: data.access_token });
      return true;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

async function request(endpoint, options = {}, { allowRefresh = true } = {}) {
  const url = `${BASE_URL}${endpoint}`;

  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  const headers = {
    ...(isFormData ? {} : { 'Content-Type': 'application/json' }),
    ...options.headers,
  };
  if (isFormData) {
    delete headers['Content-Type'];
  }

  if (csrfToken) {
    headers['X-CSRF-Token'] = csrfToken;
  }

  const storedAccess = readStorage(ACCESS_KEY);
  if (storedAccess && !headers.Authorization) {
    headers.Authorization = `Bearer ${storedAccess}`;
  }

  const config = {
    ...options,
    headers,
    credentials: 'include',
  };

  let response = await fetch(url, config);

  // Automatic seamless token refresh + 1x retry when access_token expires (60m default)
  const isAuthBypass =
    endpoint.includes('/auth/login') ||
    endpoint.includes('/auth/refresh') ||
    endpoint.includes('/auth/logout');
  if (response.status === 401 && allowRefresh && !isAuthBypass) {
    const refreshed = await performTokenRefresh();
    if (refreshed) {
      return request(endpoint, options, { allowRefresh: false });
    }
  }

  // Extract CSRF token from response header if present
  const newCsrf = response.headers.get('X-CSRF-Token');
  if (newCsrf) {
    csrfToken = newCsrf;
  }

  if (response.status === 204) {
    return null;
  }

  const rawText = await response.text();
  let data = null;
  if (rawText) {
    try {
      data = JSON.parse(rawText);
    } catch {
      data = { detail: rawText };
    }
  }

  if (!response.ok) {
    const detailMsg = typeof data?.detail === 'string'
      ? data.detail
      : Array.isArray(data?.detail)
        ? data.detail.map((d) => d.msg || JSON.stringify(d)).join('; ')
        : null;
    const message = data?.error?.message || detailMsg || `Request failed: ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}

export function getAccessToken() {
  return readStorage(ACCESS_KEY);
}

export function getApiBaseUrl() {
  return BASE_URL;
}

async function downloadBlob(endpoint, fallbackFilename = 'download', { allowRefresh = true } = {}) {
  const url = `${BASE_URL}${endpoint}`;
  const headers = {};
  if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
  const storedAccess = readStorage(ACCESS_KEY);
  if (storedAccess) headers.Authorization = `Bearer ${storedAccess}`;

  const response = await fetch(url, {
    method: 'GET',
    headers,
    credentials: 'include',
  });

  if (response.status === 401 && allowRefresh) {
    const refreshed = await performTokenRefresh();
    if (refreshed) {
      return downloadBlob(endpoint, fallbackFilename, { allowRefresh: false });
    }
  }

  if (!response.ok) {
    let message = `Download failed: ${response.status}`;
    try {
      const errData = await response.json();
      message = errData?.detail || errData?.error?.message || message;
    } catch {
      // ignore non-json
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] || fallbackFilename;

  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
  return { filename, size: blob.size };
}

export const httpClient = {
  get:    (url, opts) => request(url, { ...opts, method: 'GET' }),
  post:   (url, body, opts) => request(url, { ...opts, method: 'POST', body: JSON.stringify(body) }),
  put:    (url, body, opts) => request(url, { ...opts, method: 'PUT', body: JSON.stringify(body) }),
  patch:  (url, body, opts) => request(url, { ...opts, method: 'PATCH', body: JSON.stringify(body) }),
  delete: (url, opts) => request(url, { ...opts, method: 'DELETE' }),
  download: downloadBlob,

  // For file uploads — no JSON content type
  upload: (url, formData, opts) => request(url, {
    ...opts,
    method: 'POST',
    body: formData,
    headers: {}, // Let browser set Content-Type with boundary
  }),
};
