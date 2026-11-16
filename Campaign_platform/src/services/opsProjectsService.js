// API layer for the Operations > Projects (Research Desk) module.
// Every call goes through authFetch so the session token is attached, the same
// as the rest of the app. Contract prefix: /api/ops.

import { buildApiUrl } from "../config";
import { authFetch } from "../utils/api";

const BASE = "/api/ops";

export class OpsApiError extends Error {
  constructor(message, status = 0, detail = null, fieldErrors = {}) {
    super(message);
    this.name = "OpsApiError";
    this.status = status;
    this.detail = detail;
    // Per-field messages from a 422 ({ fieldName: message }). Empty for other errors.
    this.fieldErrors = fieldErrors;
  }
}

// FastAPI/Pydantic 422 detail: [{ loc: ["body", "field"], msg }]. The field is the
// last string element of loc (a list index such as 0 is skipped).
const fieldNameFromLoc = (loc) => {
  const parts = Array.isArray(loc) ? loc : [loc];
  for (let i = parts.length - 1; i >= 0; i -= 1) {
    if (typeof parts[i] === "string") return parts[i];
  }
  return String(parts[parts.length - 1] ?? "");
};

// Returns { message, fieldErrors } for an array detail; first message wins per field.
const parseValidationDetail = (detail) => {
  const fieldErrors = {};
  const parts = [];
  detail.forEach((item) => {
    const field = fieldNameFromLoc(item?.loc);
    const msg = typeof item?.msg === "string" ? item.msg : "is invalid";
    if (field && fieldErrors[field] === undefined) fieldErrors[field] = msg;
    parts.push(field ? `${field}: ${msg}` : msg);
  });
  return { message: parts.join("; "), fieldErrors };
};

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
  let fieldErrors = {};
  if (typeof detail === "string") message = detail;
  else if (Array.isArray(detail) && detail.length > 0) {
    ({ message, fieldErrors } = parseValidationDetail(detail));
  } else if (detail && typeof detail.message === "string") message = detail.message;
  return new OpsApiError(message, res.status, detail, fieldErrors);
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

// Single-entity endpoints wrap the entity ({project}, {survey}, ...). The
// wrappers below return the entity itself so callers never unwrap.
const pick = (key) => (res) => res?.[key] ?? null;

// Supplier buy price is a string on the wire (backend `buyPrice: str`).
// null/empty clears it; numbers are converted.
const priceString = (v) => (v === undefined ? undefined : v === null || v === "" ? null : String(v));
const supplierBody = (body) => {
  if (!body || body.buyPrice === undefined) return body;
  return { ...body, buyPrice: priceString(body.buyPrice) };
};

// ---------- Projects ----------

export const listProjects = (params) => request("/projects", { params });
export const createProject = (body) => request("/projects", { method: "POST", body }).then(pick("project"));
export const getProject = (id) => request(`/projects/${id}`).then(pick("project"));
export const updateProject = (id, body) =>
  request(`/projects/${id}`, { method: "PUT", body }).then(pick("project"));
// Returns { isFavorite } (the server flips the flag; the body is not read).
export const setProjectFavorite = (id, isFavorite) =>
  request(`/projects/${id}/favorite`, { method: "POST", body: { isFavorite } });
export const setProjectStatus = (id, status) =>
  request(`/projects/${id}/status`, { method: "POST", body: { status } }).then(pick("project"));
export const getProjectChangeLog = (id) => request(`/projects/${id}/change-log`);

// ---------- Surveys ----------

export const listSurveys = (projectId, params) =>
  request(`/projects/${projectId}/surveys`, { params });
export const createSurvey = (projectId, body) =>
  request(`/projects/${projectId}/surveys`, { method: "POST", body }).then(pick("survey"));
export const getSurvey = (id) => request(`/surveys/${id}`).then(pick("survey"));
// Returns { url }. 404 ("No survey URL set") arrives as an OpsApiError. Records no traffic.
export const getSurveyTestLink = (id) => request(`/surveys/${id}/test-link`);
export const updateSurvey = (id, body) =>
  request(`/surveys/${id}`, { method: "PUT", body }).then(pick("survey"));
export const setSurveyStatus = (id, status) =>
  request(`/surveys/${id}/status`, { method: "POST", body: { status } }).then(pick("survey"));
export const duplicateSurvey = (id) =>
  request(`/surveys/${id}/duplicate`, { method: "POST" }).then(pick("survey"));
export const getSurveyChangeLog = (id) => request(`/surveys/${id}/change-log`);

// ---------- Survey sources (suppliers) ----------

export const listSurveySuppliers = (surveyId, params) =>
  request(`/surveys/${surveyId}/suppliers`, { params });
// Returns { items: [...] }, one supplier row per vendor.
export const addSurveySuppliers = (surveyId, body) =>
  request(`/surveys/${surveyId}/suppliers`, { method: "POST", body: supplierBody(body) });
export const updateSurveySupplier = (sid, body) =>
  request(`/survey-suppliers/${sid}`, { method: "PUT", body: supplierBody(body) }).then(pick("item"));
export const deleteSurveySupplier = (sid) =>
  request(`/survey-suppliers/${sid}`, { method: "DELETE" });

// ---------- Shared lookups ----------

export const lookupVendors = (q) => request("/vendors/lookup", { params: { q } });
export const globalSearch = (q) => request("/search", { params: { q } });

// Manager dropdown: { items: [{ username, name }] }, open to any logged-in user.
export const listManagers = () => request("/managers").then((res) => unwrapList(res, "items"));

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

// Every survey in a project, paged 50 at a time. Used by the modal pickers.
export const listAllProjectSurveys = async (projectId) => {
  const items = [];
  for (let page = 1; page <= 20; page += 1) {
    const res = await listSurveys(projectId, { page, pageSize: 50, sort: "surveyName", order: "asc" });
    const batch = unwrapList(res, "items");
    items.push(...batch);
    if (batch.length < 50 || items.length >= Number(res?.total ?? 0)) break;
  }
  return items;
};

// ---------- Data cleaning requests ----------

export const listCleaningRequests = (projectId) => request(`/projects/${projectId}/cleaning-requests`);
export const createCleaningRequest = (projectId, body) =>
  request(`/projects/${projectId}/cleaning-requests`, { method: "POST", body }).then(pick("request"));
export const updateCleaningRequestStatus = (rid, body) =>
  request(`/cleaning-requests/${rid}/status`, { method: "POST", body }).then(pick("request"));

// ---------- Reconciliations (comparison only; respondent statuses are not changed) ----------

export const listReconciliations = (projectId) => request(`/projects/${projectId}/reconciliations`);
export const createReconciliation = (projectId, body) =>
  request(`/projects/${projectId}/reconciliations`, { method: "POST", body }).then(pick("reconciliation"));
export const getReconciliation = (rid) => request(`/reconciliations/${rid}`).then(pick("reconciliation"));

// ---------- Project report and survey trend ----------

export const getProjectReport = (projectId) => request(`/projects/${projectId}/report`);
export const getSurveyTrend = (surveyId, days = 14) =>
  request(`/surveys/${surveyId}/trend`, { params: { days } });

// ---------- Response helpers ----------

// Accepts either a bare array or {items} / {vendors} wrappers.
export const unwrapList = (data, ...keys) => {
  if (Array.isArray(data)) return data;
  for (const key of keys) {
    if (Array.isArray(data?.[key])) return data[key];
  }
  return [];
};
