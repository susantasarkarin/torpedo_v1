// Shared constants and formatters for the Operations > Projects (Research Desk) pages.
// Kept apart from opsShared.jsx, which exports components only (react-refresh rule).

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
