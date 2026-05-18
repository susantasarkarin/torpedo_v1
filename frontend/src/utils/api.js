/**
 * Lightweight API client for secondary frontend (frontend/src/pages/).
 *
 * Mirrors the auth and base-URL patterns from Campaign_platform/src/utils/api.js:
 *  - Reads session token from localStorage key "session_id"
 *  - Sends Authorization header on every request
 *  - On 401: clears auth and redirects to /admin/login
 *  - In development (localhost): hits http://localhost:8000
 *  - In production: uses relative URLs (nginx proxies to backend)
 */

const getApiBase = () => {
  if (
    window.location.hostname === "localhost" ||
    window.location.hostname === "127.0.0.1"
  ) {
    return "http://localhost:8000";
  }
  return "";
};

const clearAuth = () => {
  localStorage.removeItem("session_id");
  localStorage.removeItem("username");
  localStorage.removeItem("role");
};

/**
 * Fetch wrapper that injects auth header and handles 401.
 *
 * @param {string} endpoint  - Path starting with "/" e.g. "/api/mail/summary"
 * @param {RequestInit} [options] - Standard fetch options (method, body, headers…)
 * @returns {Promise<Response>}
 */
export const apiFetch = async (endpoint, options = {}) => {
  const base = getApiBase();
  const url = `${base}${endpoint.startsWith("/") ? endpoint : "/" + endpoint}`;

  const sessionId = localStorage.getItem("session_id");

  const headers = {
    "Content-Type": "application/json",
    ...(sessionId ? { Authorization: sessionId } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(url, { ...options, headers });

  if (response.status === 401) {
    clearAuth();
    window.location.href = "/admin/login";
  }

  return response;
};

export default apiFetch;
