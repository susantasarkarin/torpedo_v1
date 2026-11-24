import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"

// Shared helpers for the Marketing pages.

// Business units, as stored in the `bu` field of every marketing record (backend marketing/schema.py BUS).
export const BUS = ["SFW", "COGENTIX", "BIM"]
export const BU_NAMES = { SFW: "Survey Fieldwork", COGENTIX: "Cogentix Research", BIM: "BimWave" }

// JSON client bound to an API prefix, e.g. marketingApi("/api/marketing/content").
// Throws an Error carrying the server's `detail` when the response is not OK.
export const marketingApi = (prefix) => async (path = "", opts = {}) => {
  const res = await authFetch(buildApiUrl(`${prefix}${path}`), {
    headers: { "Content-Type": "application/json" }, ...opts,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`)
  return data
}
