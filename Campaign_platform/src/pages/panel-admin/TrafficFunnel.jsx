import { useEffect, useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

/**
 * Traffic funnel — every landing on the SFW panel site is a visit record
 * (source, country, the ad platform's respondent id, device), followed through
 * form started → signup → email verified → membership confirmed (double opt-in:
 * email, mobile, consents) → profile complete. Data comes from
 * the panel's /api/admin/traffic via Torpedo's proxy.
 */

const card = {
  background: "#fff",
  border: "1px solid #e8e4dc",
  borderRadius: "10px",
  padding: "1.25rem",
  marginBottom: "1.25rem",
}
const th = { textAlign: "left", padding: "0.5rem 0.6rem", fontSize: "0.8rem", color: "#5c5c5c", borderBottom: "1px solid #e8e4dc", whiteSpace: "nowrap" }
const td = { padding: "0.5rem 0.6rem", fontSize: "0.875rem", color: "#1a1a1a", borderBottom: "1px solid #f5f3ef", whiteSpace: "nowrap" }

const STEPS = [
  ["visits", "Visits"],
  ["formStarted", "Form started"],
  ["signups", "Signed up"],
  ["verified", "Email verified"],
  ["membershipConfirmed", "Membership confirmed"],
  ["profileCompleted", "Profile complete"],
]

const pct = (n, d) => (d > 0 ? `${((n / d) * 100).toFixed(1)}%` : "—")

function FunnelTable({ title, rows, keyLabel }) {
  return (
    <div style={card}>
      <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>{title}</h3>
      {rows.length === 0 ? (
        <p style={{ color: "#5c5c5c", fontSize: "0.875rem", margin: 0 }}>No visits in this window.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={th}>{keyLabel}</th>
                {STEPS.map(([k, label]) => <th key={k} style={th}>{label}</th>)}
                <th style={th}>Visit → verified</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td style={{ ...td, fontWeight: 600 }}>{r.key}</td>
                  {STEPS.map(([k]) => <td key={k} style={td}>{(r[k] || 0).toLocaleString()}</td>)}
                  <td style={td}>{pct(r.verified, r.visits)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function TrafficFunnel({ embedded = false }) {
  const [days, setDays] = useState(30)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

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

  return (
    <div style={{ padding: embedded ? 0 : "1.5rem", maxWidth: "1200px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "1rem" }}>
        <div>
          {!embedded && <h2 style={{ margin: 0 }}>Traffic Funnel</h2>}
          <p style={{ margin: "0.25rem 0 0", color: "#5c5c5c", fontSize: "0.875rem" }}>
            Every landing on surveyfieldwork.com, by ad source and country. Respondent id = the ad platform's click id (Meta fbclid, Quora qclid) or ?rid=.
          </p>
        </div>
        <select value={days} onChange={(e) => setDays(Number(e.target.value))}
          style={{ padding: "0.45rem 0.6rem", border: "1px solid #d4cec3", borderRadius: "6px", fontSize: "0.875rem" }}>
          {[1, 7, 30, 90, 180].map((d) => <option key={d} value={d}>Last {d} day{d > 1 ? "s" : ""}</option>)}
        </select>
      </div>

      {error && <div style={{ ...card, borderColor: "#fecaca", background: "#fef2f2", color: "#991b1b" }}>{error}</div>}
      {loading && !data && <p style={{ color: "#5c5c5c" }}>Loading…</p>}

      {totals && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "0.75rem", marginBottom: "1.25rem" }}>
          {STEPS.map(([k, label], i) => (
            <div key={k} style={{ ...card, marginBottom: 0 }}>
              <div style={{ fontSize: "0.8rem", color: "#5c5c5c", fontWeight: 600 }}>{label}</div>
              <div style={{ fontSize: "1.6rem", fontWeight: 700, marginTop: "0.2rem" }}>{(totals[k] || 0).toLocaleString()}</div>
              {i > 0 && <div style={{ fontSize: "0.8rem", color: "#5c5c5c" }}>{pct(totals[k], totals[STEPS[i - 1][0]])} of previous</div>}
            </div>
          ))}
        </div>
      )}

      {data && (
        <>
          <FunnelTable title="By ad source" keyLabel="Source" rows={data.bySource} />
          <FunnelTable title="By country" keyLabel="Country" rows={data.byCountry} />
          <FunnelTable title="By device" keyLabel="Device" rows={data.byDevice} />
          <FunnelTable title="By day" keyLabel="Date" rows={[...data.daily].reverse()} />

          <div style={card}>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>Latest visits</h3>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    {["Time (IST)", "Source", "Country", "IP country", "Respondent id", "Campaign", "Device", "Stage"].map((h) => <th key={h} style={th}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {data.recent.map((v, i) => (
                    <tr key={i}>
                      <td style={td}>{new Date(v.createdAt).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "short", timeStyle: "short" })}</td>
                      <td style={td}>{v.source || "direct"}</td>
                      <td style={td}>{v.country || "—"}</td>
                      <td style={td}>{v.ipCountry || "—"}</td>
                      <td style={{ ...td, fontFamily: "ui-monospace, Menlo, monospace", maxWidth: "14rem", overflow: "hidden", textOverflow: "ellipsis" }} title={v.respondentId || ""}>
                        {v.respondentId ? `${v.respondentId}${v.clickIdType ? ` (${v.clickIdType})` : ""}` : "—"}
                      </td>
                      <td style={td}>{v.utm?.campaign || "—"}</td>
                      <td style={td}>{[v.device?.type, v.device?.os, v.device?.browser].filter(Boolean).join(" · ") || "—"}</td>
                      <td style={td}>{(v.stage || "").replace(/_/g, " ")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
