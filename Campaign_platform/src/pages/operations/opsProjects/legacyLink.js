// Creates a classic traffic link (a legacy `projects` record, one per vendor) the same
// way Operations > Projects (classic) does, so a supplier added in the new flow gets a
// real link number (surveyNo) and entry link. Derivations mirror ProjectsPage.jsx.

import { buildApiUrl } from "../../../config";
import { authFetch } from "../../../utils/api";

const callbackBase = () =>
  typeof window !== "undefined" && window.location?.origin
    ? window.location.origin.replace(/\/$/, "")
    : "https://surveyfieldwork.com";

const isCint = (liveLink) => {
  const link = String(liveLink || "").trim().toLowerCase();
  if (!link) return false;
  try {
    const host = new URL(link).hostname;
    if (host.includes("samplicio.us") || host.includes("cint") || host.includes("luc.id")) return true;
  } catch {
    // malformed URL: fall through to the substring check
  }
  return link.includes("cint");
};

export const systemPages = (liveLink) => {
  const base = callbackBase();
  if (isCint(liveLink)) {
    return {
      completePage: `${base}/cint-response?status=complete&pid=[%PID%]&mid=[%MID%]&revenue=[%REVENUE%]`,
      terminatePage: `${base}/cint-response?status=terminate&pid=[%PID%]&mid=[%MID%]`,
      quotaFullPage: `${base}/cint-response?status=quota_full&pid=[%PID%]&mid=[%MID%]`,
    };
  }
  return {
    completePage: `${base}/surveycomplete?rid={RID}`,
    terminatePage: `${base}/surveyterminate?rid={RID}`,
    quotaFullPage: `${base}/surveyquotafull?rid={RID}`,
    securityTerminatePage: `${base}/surveyterminate?rid={RID}&type=security`,
  };
};

// pid is filled in by the server (it replaces pid= with the new surveyNo on create).
export const entryLinkTemplate = (vid, surveyNo) =>
  `${callbackBase()}/takesurvey?api=false&vid=${vid || "{VID}"}&cc=[%CC%]&panel=[%PANEL%]&pid=${surveyNo || "{PID}"}&rid=[%RID%]`;

export const normalizeUrl = (value) => {
  const raw = String(value || "").trim();
  if (!raw) return "";
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `https://${raw}`;
};

const asList = (v) => (Array.isArray(v) ? v.filter(Boolean) : v ? [v] : []);

const call = async (path, options = {}) => {
  const res = await authFetch(buildApiUrl(path), {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: localStorage.getItem("session_id") || "" },
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
};

// Full vendor record (redirect lists) by vid; the ops lookup returns names only.
export const fetchVendorByVid = async (vid) => {
  const data = await call("/api/vendors/");
  const list = Array.isArray(data) ? data : data.vendors || [];
  return list.find((v) => String(v.vid) === String(vid)) || null;
};

// POST /projects/ exactly as the classic page does. Returns the saved record
// ({ _id, surveyNo, entryLink, ... }).
export const createLegacyLink = async (form, vendor) => {
  const liveLink = normalizeUrl(form.liveLink);
  const payload = {
    projectName: form.projectName.trim(),
    client: form.client.trim(),
    salesPerson: form.salesPerson.trim(),
    projectStatus: "live",
    projectLaunchDate: form.projectLaunchDate,
    projectCloseDate: "",
    totalCompletesRequired: form.totalCompletesRequired,
    totalCompletes: form.totalCompletesRequired,
    loi: form.loi,
    clientIR: form.clientIR,
    cpi: form.cpi,
    countryCode: form.countryCode.trim().toUpperCase(),
    liveLink,
    entryLink: entryLinkTemplate(vendor.vid, "new"), // server swaps pid= for the new surveyNo
    ...systemPages(liveLink),
    vendorName: vendor.vendorName || "",
    vendorId: String(vendor.vid || ""),
    vendorCompleteRD: asList(vendor.completeRD),
    vendorTerminateRD: asList(vendor.terminateRD),
    vendorQuotaFullRD: asList(vendor.quotaRD || vendor.quotaFullRD),
    routingEnabled: false,
    qualification: { enabled: false, ageMin: "", ageMax: "", genders: [], employment: [], occupation: [], custom: [] },
  };
  const data = await call("/projects/", { method: "POST", body: JSON.stringify(payload) });
  return data.project;
};

// Undo a just-created link when attaching it to the survey fails (soft delete).
export const deleteLegacyLink = (id) => call(`/projects/${id}`, { method: "DELETE" }).catch(() => {});
