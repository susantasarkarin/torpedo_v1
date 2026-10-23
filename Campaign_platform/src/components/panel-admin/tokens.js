import { useSearchParams } from "react-router-dom"

// Shared style tokens, country names and the URL-backed tab hook for the Panel module.

export const colors = {
  text: "#111827",
  muted: "#6f6f6f",
  border: "#e8e4dc",
  accent: "#4f46e5",
  good: "#15803d",
  warn: "#d97706",
  bad: "#dc2626",
}

export const card = { background: "#fff", border: `1px solid ${colors.border}`, borderRadius: "10px", padding: "1.25rem", marginBottom: "1.25rem" }
export const th = { textAlign: "left", padding: "0.5rem 0.6rem", fontSize: "0.8rem", color: "#5c5c5c", borderBottom: `1px solid ${colors.border}`, whiteSpace: "nowrap" }
export const td = { padding: "0.5rem 0.6rem", fontSize: "0.875rem", color: colors.text, borderBottom: "1px solid #f5f3ef" }

export const COUNTRY_NAMES = {
  US: "United States", IN: "India", GB: "United Kingdom", UK: "United Kingdom", AU: "Australia",
  CA: "Canada", DE: "Germany", FR: "France", SG: "Singapore", AE: "UAE", ES: "Spain", NG: "Nigeria",
  XX: "Unknown", "??": "Unknown", Unknown: "Unknown",
}
export const countryName = (code) => COUNTRY_NAMES[code] || code || "Unknown"

// Tabs whose selection lives in the URL (?tab=...), so a section can be linked to.
export function useTab(tabs) {
  const [params, setParams] = useSearchParams()
  const keys = tabs.map((t) => t.key)
  const active = keys.includes(params.get("tab")) ? params.get("tab") : keys[0]
  const setActive = (key) => setParams(key === keys[0] ? {} : { tab: key }, { replace: true })
  return [active, setActive]
}

