import { useEffect, useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"
import { colors, card, control, th, td } from "../../components/panel-admin/tokens"
import { SectionHeader, StatTile, TileRow, Notice, Segmented } from "../../components/panel-admin/ui"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

/**
 * Traffic funnel — every landing on the SFW panel site is a visit record
 * (source, country, the ad platform's respondent id, device), followed through
 * form started → signup → email verified → membership confirmed (double opt-in:
 * email, mobile, consents) → profile complete. Data comes from
 * the panel's /api/admin/traffic via Torpedo's proxy.
 */

const cell = { ...td, whiteSpace: "nowrap" }

const STEPS = [
  ["visits", "Visits"],
  ["formStarted", "Form started"],
  ["signups", "Signed up"],
  ["verified", "Email verified"],
  ["membershipConfirmed", "Membership confirmed"],
  ["profileCompleted", "Profile complete"],
]

// One breakdown table at a time instead of four stacked ones.
const BREAKDOWNS = [
  { key: "bySource", label: "Ad source", column: "Source" },
  { key: "byCountry", label: "Country", column: "Country" },
  { key: "byDevice", label: "Device", column: "Device" },
  { key: "daily", label: "Day", column: "Date", newestFirst: true },
]

const pct = (n, d) => (d > 0 ? `${((n / d) * 100).toFixed(1)}%` : "—")

function FunnelTable({ rows, keyLabel }) {
  if (rows.length === 0) {
    return <p style={{ color: colors.muted, fontSize: "0.875rem", margin: 0 }}>No visits in this window.</p>
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={th}>{keyLabel}</th>
            {STEPS.map(([k, label]) => <th key={k} style={{ ...th, textAlign: "right" }}>{label}</th>)}
            <th style={{ ...th, textAlign: "right" }}>Visit → verified</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <td style={{ ...cell, fontWeight: 600 }}>{r.key}</td>
              {STEPS.map(([k]) => <td key={k} style={{ ...cell, textAlign: "right" }}>{(r[k] || 0).toLocaleString()}</td>)}
              <td style={{ ...cell, textAlign: "right", fontWeight: 600 }}>{pct(r.verified, r.visits)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function TrafficFunnel({ embedded = false }) {
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [breakdown, setBreakdown] = useState("bySource")

  useEffect(() => {
    let active = true
    setLoading(true)
    setError("")
    authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/traffic?days=${days}`))
      .then(async (res) => {
        const body = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`)
        return body
      })
      .then((body) => active && setData(body))
      .catch((e) => active && setError(e.message))
      .finally(() => active && setLoading(false))
    return () => { active = false }
  }, [days])

  const totals = data?.totals
  const current = BREAKDOWNS.find((b) => b.key === breakdown)
  // A missing list (older panel API, partial response) renders as empty instead of crashing the tab.
  const rows = data?.[current.key] || []
  const recent = data?.recent || []

  return (
    <div style={{ padding: embedded ? 0 : "1.5rem", maxWidth: "1200px", opacity: loading && data ? 0.6 : 1, transition: "opacity 0.15s" }}>
      <SectionHeader
        title={embedded ? "Landing traffic" : "Traffic Funnel"}
        description="Every landing on surveyfieldwork.com, by ad source and country. Respondent id = the ad platform's click id (Meta fbclid, Quora qclid) or ?rid=."
        actions={
          <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))} style={control}>
            {[1, 7, 30, 90, 180].map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>)}
          </select>
        }
      />

      {error && <Notice tone="bad" style={{ marginBottom: "1rem" }}>{error}</Notice>}
      {loading && !data && <p style={{ color: colors.muted }}>Loading…</p>}

      {totals && (
        <TileRow min={150}>
          {STEPS.map(([k, label], i) => (
            <StatTile
              key={k}
              label={label}
              value={(totals[k] || 0).toLocaleString()}
              sub={i > 0 ? `${pct(totals[k], totals[STEPS[i - 1][0]])} of previous` : null}
            />
          ))}
        </TileRow>
      )}

      {data && (
        <>
          <div style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem", flexWrap: "wrap", marginBottom: "0.9rem" }}>
              <h3 style={{ margin: 0, fontSize: "1rem", color: colors.text }}>Funnel by {current.label.toLowerCase()}</h3>
              <Segmented label="Break down by" options={BREAKDOWNS} value={breakdown} onChange={setBreakdown} />
            </div>
            <FunnelTable keyLabel={current.column} rows={current.newestFirst ? [...rows].reverse() : rows} />
          </div>

          <div style={card}>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem", color: colors.text }}>Latest visits</h3>
            {recent.length === 0 ? (
              <p style={{ color: colors.muted, fontSize: "0.875rem", margin: 0 }}>No visits in this window.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["Time (IST)", "Source", "Country", "IP country", "Respondent id", "Campaign", "Device", "Stage"].map((h) => <th key={h} style={th}>{h}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map((v, i) => (
                      <tr key={i}>
                        <td style={cell}>{new Date(v.createdAt).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "short", timeStyle: "short" })}</td>
                        <td style={cell}>{v.source || "direct"}</td>
                        <td style={cell}>{v.country || "—"}</td>
                        <td style={cell}>{v.ipCountry || "—"}</td>
                        <td style={{ ...cell, fontFamily: "ui-monospace, Menlo, monospace", maxWidth: "14rem", overflow: "hidden", textOverflow: "ellipsis" }} title={v.respondentId || ""}>
                          {v.respondentId ? `${v.respondentId}${v.clickIdType ? ` (${v.clickIdType})` : ""}` : "—"}
                        </td>
                        <td style={cell}>{v.utm?.campaign || "—"}</td>
                        <td style={cell}>{[v.device?.type, v.device?.os, v.device?.browser].filter(Boolean).join(" · ") || "—"}</td>
                        <td style={cell}>{(v.stage || "").replace(/_/g, " ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
