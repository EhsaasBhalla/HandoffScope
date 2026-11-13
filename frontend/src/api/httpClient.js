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
    return typeof window !== 'undefined' ? window.localStorage?.getItem(key) || null : null;
  } catch {
    return null;
  }
}

function writeStorage(key, val) {
  try {
    if (typeof window === 'undefined') return;
    if (val) {
      window.localStorage?.setItem(key, val);
    } else {
      window.localStorage?.removeItem(key);
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

      const newCsrf = res.headers.get('X-CSRF-Token');
      if (newCsrf) setCsrfToken(newCsrf);

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

  // If 401 persists after retry, or refresh failed/bypassed, dispatch expiry event
  if (response.status === 401 && !isAuthBypass) {
    clearAuthTokens();
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('handoffscope:auth-expired'));
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
        ? data.detail.map((d) => (d && typeof d === 'object' ? d.msg || JSON.stringify(d) : String(d))).join('; ')
        : (data?.detail && typeof data?.detail === 'object')
          ? (data.detail.message || JSON.stringify(data.detail))
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

export function getRefreshToken() {
  return readStorage(REFRESH_KEY);
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

  if (response.status === 401) {
    if (allowRefresh) {
      const refreshed = await performTokenRefresh();
      if (refreshed) {
        return downloadBlob(endpoint, fallbackFilename, { allowRefresh: false });
      }
    }
    clearAuthTokens();
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('handoffscope:auth-expired'));
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
  let filename = fallbackFilename;
  const disposition = response.headers.get('Content-Disposition') || '';
  const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      filename = decodeURIComponent(utf8Match[1].trim());
    } catch {
      filename = utf8Match[1].trim();
    }
  } else {
    const match = disposition.match(/filename=(?:(["'])(.*?)\1|([^;\n]*))/i);
    const candidate = match?.[2] || match?.[3];
    if (candidate) filename = candidate.trim();
  }

  if (typeof document !== 'undefined') {
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
  }
  return { filename, size: blob.size };
}

export const httpClient = {
  get:    (url, opts) => request(url, { ...opts, method: 'GET' }),
  post:   (url, body, opts) => request(url, { ...opts, method: 'POST', body: body !== undefined ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined }),
  put:    (url, body, opts) => request(url, { ...opts, method: 'PUT', body: body !== undefined ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined }),
  patch:  (url, body, opts) => request(url, { ...opts, method: 'PATCH', body: body !== undefined ? (typeof body === 'string' ? body : JSON.stringify(body)) : undefined }),
  delete: (url, opts) => request(url, { ...opts, method: 'DELETE' }),
  download: downloadBlob,

  // For file uploads — preserve custom headers and method override
  upload: (url, formData, opts = {}) => request(url, {
    ...opts,
    method: opts.method || 'POST',
    body: formData,
    headers: { ...opts.headers },
  }),
};
