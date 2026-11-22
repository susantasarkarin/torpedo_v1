import { useSearchParams } from "react-router-dom"

// Shared style tokens, country names and the URL-backed tab hook for the Panel module.

export const colors = {
  text: "#1a1a1a",
  muted: "#6f6f6f",
  border: "#e8e4dc",
  accent: "#a15f06",  // brand orange for text (fills use #e8910a)
  good: "#15803d",
  warn: "#d97706",
  bad: "#dc2626",
}

// Tinted fills for badges and notices (bg = fill, fg = text, border).
export const tones = {
  good: { bg: "#dcfce7", fg: "#166534", border: "#bbf7d0" },
  warn: { bg: "#fef3c7", fg: "#92400e", border: "#fcd34d" },
  bad: { bg: "#fee2e2", fg: "#991b1b", border: "#fecaca" },
  accent: { bg: "#fdf4e7", fg: "#a15f06", border: "#f3d9ad" },
  neutral: { bg: "#f5f3ef", fg: "#5c5c5c", border: "#e8e4dc" },
}

// Inputs and selects share one look.
export const control = { padding: "0.55rem 0.75rem", border: "1px solid #d4cec3", borderRadius: "6px", fontSize: "0.875rem", backgroundColor: "#fff", color: colors.text, boxSizing: "border-box" }

export const card = { background: "#fff", border: `1px solid ${colors.border}`, borderRadius: "10px", padding: "1.25rem", marginBottom: "1.25rem" }
export const th = { textAlign: "left", padding: "0.5rem 0.6rem", fontSize: "0.8rem", color: "#5c5c5c", borderBottom: `1px solid ${colors.border}`, whiteSpace: "nowrap" }
export const td = { padding: "0.5rem 0.6rem", fontSize: "0.875rem", color: colors.text, borderBottom: "1px solid #f5f3ef" }

export const COUNTRY_NAMES = {
  US: "United States", IN: "India", GB: "United Kingdom", UK: "United Kingdom", AU: "Australia",
  CA: "Canada", DE: "Germany", FR: "France", SG: "Singapore", AE: "UAE", ES: "Spain", NG: "Nigeria",
  XX: "Unknown", "??": "Unknown", Unknown: "Unknown",
}
const REGION_NAMES = (() => {
  try { return new Intl.DisplayNames(["en"], { type: "region" }) } catch { return null }
})()
// Any ISO code (MG → Madagascar) via the browser's own country names.
export const countryName = (code) => {
  if (COUNTRY_NAMES[code]) return COUNTRY_NAMES[code]
  if (!code) return "Unknown"
  try { return (/^[A-Z]{2}$/.test(code) && REGION_NAMES && REGION_NAMES.of(code)) || code } catch { return code }
}

// Tabs whose selection lives in the URL (?tab=...), so a section can be linked to.
export function useTab(tabs) {
  const [params, setParams] = useSearchParams()
  const keys = tabs.map((t) => t.key)
  const active = keys.includes(params.get("tab")) ? params.get("tab") : keys[0]
  const setActive = (key) => setParams(key === keys[0] ? {} : { tab: key }, { replace: true })
  return [active, setActive]
}

