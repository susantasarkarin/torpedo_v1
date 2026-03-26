/**
 * QRE Survey Platform API client
 * Handles all communication with the QRE backend (runs on a separate port).
 *
 * In development  : QRE backend defaults to http://localhost:8001
 * In production   : set VITE_QRE_API_URL env var or rely on nginx proxy at /qre-api/
 */

const QRE_API_BASE = (() => {
  if (import.meta.env.VITE_QRE_API_URL) return import.meta.env.VITE_QRE_API_URL;
  if (typeof window !== "undefined" && window.location.hostname === "localhost") {
    return "http://localhost:8001";
  }
  return "/qre-api"; // nginx proxy path in production
})();

let _token = "";

async function req(method, path, body = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
  };
  if (_token) opts.headers["Authorization"] = `Bearer ${_token}`;
  if (body !== null) opts.body = JSON.stringify(body);

  const res = await fetch(`${QRE_API_BASE}${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "QRE API request failed");
  }
  return res.json();
}

export const qreApi = {
  setToken: (t) => { _token = t; },

  // --- Auth ---
  login: (username, password) =>
    req("POST", "/api/auth/login", { username, password }),

  // --- Studies ---
  listStudies: () => req("GET", "/api/studies/"),
  createStudy: (payload) => req("POST", "/api/studies/", payload),
  getStudy: (id) => req("GET", `/api/studies/${id}`),
  updateStudy: (id, fields) => req("PATCH", `/api/studies/${id}`, fields),
  deleteStudy: (id) => req("DELETE", `/api/studies/${id}`),

  // --- Stats (global / per-study) ---
  getStats: (studyId) =>
    studyId ? req("GET", `/api/studies/${studyId}/stats`) : req("GET", "/api/admin/stats"),
  getDashboard: (studyId) =>
    studyId ? req("GET", `/api/studies/${studyId}/dashboard`) : req("GET", "/api/admin/dashboard"),

  // --- Quotas ---
  getQuotas: (studyId) =>
    studyId ? req("GET", `/api/studies/${studyId}/quotas`) : req("GET", "/api/admin/quotas"),
  getQuotaLimits: () => req("GET", "/api/admin/quotas/limits"),
  updateQuota: (quotaKey, limit, studyId) =>
    studyId
      ? req("POST", `/api/studies/${studyId}/quotas/update`, { quota_key: quotaKey, limit })
      : req("POST", "/api/admin/quotas/update", { quota_key: quotaKey, limit }),
  resetQuotas: (studyId) =>
    studyId
      ? req("POST", `/api/studies/${studyId}/quotas/reset`)
      : req("POST", "/api/admin/quotas/reset"),

  // --- Redirects ---
  getRedirects: (studyId) =>
    studyId ? req("GET", `/api/studies/${studyId}/redirects`) : req("GET", "/api/admin/redirects"),
  setRedirects: (config, studyId) =>
    studyId
      ? req("POST", `/api/studies/${studyId}/redirects`, config)
      : req("POST", "/api/admin/redirects", config),

  // --- Export ---
  exportUrl: (type, studyId) => {
    const base = `${QRE_API_BASE}/api/admin`;
    if (type === "completed") return studyId ? `${base}/export?study_id=${studyId}` : `${base}/export`;
    if (type === "spss") return `${base}/export/spss`;
    return studyId ? `${base}/export/all?study_id=${studyId}` : `${base}/export/all`;
  },

  /** Authenticated download: fetches with Bearer token and triggers browser save. */
  downloadExport: async (type, studyId, filename) => {
    const base = `${QRE_API_BASE}/api/admin`;
    let url;
    if (type === "completed") url = studyId ? `${base}/export?study_id=${studyId}` : `${base}/export`;
    else if (type === "spss") url = `${base}/export/spss`;
    else url = studyId ? `${base}/export/all?study_id=${studyId}` : `${base}/export/all`;

    const res = await fetch(url, {
      headers: _token ? { Authorization: `Bearer ${_token}` } : {},
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Export failed");
    }
    const blob = await res.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = filename || "export";
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(objUrl); document.body.removeChild(a); }, 1000);
  },
};
