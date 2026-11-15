// API layer for the Operations > Projects (Research Desk) module.
// Every call goes through authFetch so the session token is attached, the same
// as the rest of the app. Contract prefix: /api/ops.

import { buildApiUrl } from "../config";
import { authFetch } from "../utils/api";

const BASE = "/api/ops";

export class OpsApiError extends Error {
  constructor(message, status = 0, detail = null) {
    super(message);
    this.name = "OpsApiError";
    this.status = status;
    this.detail = detail;
  }
}

const toQuery = (params = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    qs.set(key, String(value));
  });
  const s = qs.toString();
  return s ? `?${s}` : "";
};

const readError = async (res) => {
  let detail = null;
  try {
    const body = await res.json();
    detail = body?.detail ?? body?.message ?? body?.error ?? null;
  } catch {
    // Non-JSON error body: fall through to the generic message.
  }
  let message = `Request failed (${res.status})`;
  if (typeof detail === "string") message = detail;
  else if (detail && typeof detail.message === "string") message = detail.message;
  return new OpsApiError(message, res.status, detail);
};

const request = async (path, { method = "GET", body, params } = {}) => {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await authFetch(buildApiUrl(`${BASE}${path}${toQuery(params)}`), init);
  } catch {
    throw new OpsApiError("Network error. Check your connection and try again.", 0);
  }
  if (!res.ok) throw await readError(res);
  if (res.status === 204) return null;
  return res.json();
};

// ---------- Projects ----------

export const listProjects = (params) => request("/projects", { params });
export const createProject = (body) => request("/projects", { method: "POST", body });
export const getProject = (id) => request(`/projects/${id}`);
export const updateProject = (id, body) => request(`/projects/${id}`, { method: "PUT", body });
export const setProjectFavorite = (id, isFavorite) =>
  request(`/projects/${id}/favorite`, { method: "POST", body: { isFavorite } });
export const setProjectStatus = (id, status) =>
  request(`/projects/${id}/status`, { method: "POST", body: { status } });
export const getProjectChangeLog = (id) => request(`/projects/${id}/change-log`);

// ---------- Surveys ----------

export const listSurveys = (projectId, params) =>
  request(`/projects/${projectId}/surveys`, { params });
export const createSurvey = (projectId, body) =>
  request(`/projects/${projectId}/surveys`, { method: "POST", body });
export const getSurvey = (id) => request(`/surveys/${id}`);
export const updateSurvey = (id, body) => request(`/surveys/${id}`, { method: "PUT", body });
export const setSurveyStatus = (id, status) =>
  request(`/surveys/${id}/status`, { method: "POST", body: { status } });
export const duplicateSurvey = (id) => request(`/surveys/${id}/duplicate`, { method: "POST" });
export const getSurveyChangeLog = (id) => request(`/surveys/${id}/change-log`);

// ---------- Survey sources (suppliers) ----------

export const listSurveySuppliers = (surveyId, params) =>
  request(`/surveys/${surveyId}/suppliers`, { params });
export const addSurveySuppliers = (surveyId, body) =>
  request(`/surveys/${surveyId}/suppliers`, { method: "POST", body });
export const updateSurveySupplier = (sid, body) =>
  request(`/survey-suppliers/${sid}`, { method: "PUT", body });
export const deleteSurveySupplier = (sid) =>
  request(`/survey-suppliers/${sid}`, { method: "DELETE" });

// ---------- Shared lookups ----------

export const lookupVendors = (q) => request("/vendors/lookup", { params: { q } });
export const globalSearch = (q) => request("/search", { params: { q } });

// Users for the manager dropdown: same endpoint UserManagement.jsx uses.
export const listUsers = async () => {
  const res = await authFetch(buildApiUrl("/admin/users/"));
  if (!res.ok) throw await readError(res);
  const data = await res.json();
  return Array.isArray(data) ? data : data.users || [];
};

// ---------- Traffic report (blob download) ----------

export const downloadTrafficReport = async (
  surveyId,
  { supplierId, format = "csv", includeAnswers = true } = {}
) => {
  const query = toQuery({ supplierId, format, includeAnswers: includeAnswers ? "true" : "false" });
  let res;
  try {
    res = await authFetch(buildApiUrl(`${BASE}/surveys/${surveyId}/traffic-report${query}`));
  } catch {
    throw new OpsApiError("Network error. Check your connection and try again.", 0);
  }
  if (!res.ok) throw await readError(res);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match ? match[1] : `traffic-report-${surveyId}.${format}`;
  return { blob, filename };
};

// Saves a blob through a temporary object URL. Kept here so pages do not repeat it.
export const saveBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
};

// ---------- Response helpers ----------

// Accepts either a bare array or {items} / {vendors} wrappers.
export const unwrapList = (data, ...keys) => {
  if (Array.isArray(data)) return data;
  for (const key of keys) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
};
