// Shared constants and formatters for the Operations > Projects (Research Desk) pages.
// Kept apart from opsShared.jsx, which exports components only (react-refresh rule).

import { getSurveyTestLink, OpsApiError } from "../../../services/opsProjectsService";
import { notify } from "../../../utils/notify";

export const NOT_CONFIRMED_TIP = "definition not yet confirmed";

// Only these roles see buy price / expense. Read from the role the login stored.
export const canSeePricing = () => {
  try {
    const role = (localStorage.getItem("role") || "").toLowerCase();
    return role === "admin" || role === "finance";
  } catch {
    return false;
  }
};

// Formatters: null means "not yet confirmed", never 0.
export const fmtInt = (v) => (v === null || v === undefined ? null : Number(v).toLocaleString());
export const fmtPct = (v) => (v === null || v === undefined ? null : `${Number(v).toFixed(1)}%`);
export const fmtLoi = (v) => (v === null || v === undefined ? null : `${Number(v).toFixed(1)} min`);
export const fmtMoney = (v, currency) => {
  if (v === null || v === undefined) return null;
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(Number(v));
  } catch {
    return `${Number(v).toFixed(2)} ${currency || ""}`.trim();
  }
};
export const fmtDateTime = (v) => {
  if (!v) return "—";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString();
};

// Splits a 422's per-field errors. Fields that match a form input (formKeys, after
// keyMap renames the API name) go under that input; the rest become one summary line.
export const splitFieldErrors = (fieldErrors = {}, formKeys = [], keyMap = {}) => {
  const inline = {};
  const other = [];
  Object.entries(fieldErrors || {}).forEach(([field, msg]) => {
    const key = keyMap[field] ?? field;
    if (formKeys.includes(key)) inline[key] = msg;
    else other.push(`${field}: ${msg}`);
  });
  return { inline, other: other.join("; ") };
};

// Fetches the survey's test link and opens it in a new tab. Records no traffic.
export const TEST_LINK_TIP = "Opens the survey link in a new tab. No traffic is recorded.";
export const openSurveyTestLink = async (surveyId) => {
  try {
    const res = await getSurveyTestLink(surveyId);
    if (!res?.url) throw new OpsApiError("No survey URL set");
    window.open(res.url, "_blank", "noopener,noreferrer");
  } catch (e) {
    notify(e.message || "Could not open the survey link.", "error");
  }
};

// Change-log values can be strings, numbers, booleans, objects or null.
export const fmtChangeValue = (v) => {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
};

export const STATUS_LABELS = {
  live: "Live",
  paused: "Paused",
  completed: "Completed",
  draft: "Draft",
  cancelled: "Cancelled",
  auto_paused: "Auto-paused",
  scheduled: "Scheduled",
  all: "All",
};
