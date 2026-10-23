import { useCallback, useEffect, useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

/**
 * Rewards & Points — live from the SurveyFieldwork Panel: points members have
 * earned, points on hold (profile not complete yet), redemptions, and the
 * Amazon gift cards still to be sent.
 */

const card = { background: "#fff", border: "1px solid #e8e4dc", borderRadius: "10px", padding: "1.25rem", marginBottom: "1.25rem" }
const th = { textAlign: "left", padding: "0.5rem 0.6rem", fontSize: "0.8rem", color: "#5c5c5c", borderBottom: "1px solid #e8e4dc", whiteSpace: "nowrap" }
const td = { padding: "0.5rem 0.6rem", fontSize: "0.875rem", color: "#1a1a1a", borderBottom: "1px solid #f5f3ef" }
const btn = { padding: "0.35rem 0.75rem", borderRadius: "6px", border: "1px solid #e8910a", background: "#e8910a", color: "#fff", cursor: "pointer", fontSize: "0.8rem" }
const COUNTRY_LABELS = { IN: "India", UK: "United Kingdom", GB: "United Kingdom", US: "United States" }
const n = (v) => (v || 0).toLocaleString()

function RewardsPoints({ embedded = false }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState("")
  const [filter, setFilter] = useState("toSend")
  const [busy, setBusy] = useState("")

  const load = useCallback(async () => {
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panel-rewards`), { headers: { Authorization: localStorage.getItem("session_id") } })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`)
      setData(body)
      setError("")
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // action: "sent" | "hold" | "release"
  const act = async (r, action) => {
    let body
    if (action === "sent" && !window.confirm(`Mark the ${r.giftCard} gift card for ${r.name || r.email} as sent?`)) return
    if (action === "hold") {
      const reason = window.prompt(`Why hold the ${r.giftCard} gift card for ${r.name || r.email}?`, "Manual review")
      if (reason === null) return
      body = JSON.stringify({ reason })
    }
    if (action === "release" && !window.confirm(`Release the hold? The ${r.giftCard} gift card can then be sent.`)) return
    setBusy(r.id)
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panel-redemptions/${r.id}/${action}`), {
        method: "POST",
        headers: { Authorization: localStorage.getItem("session_id"), "Content-Type": "application/json" },
        body,
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || `HTTP ${res.status}`)
      }
      await load()
    } catch (e) {
      alert(`Could not ${action === "sent" ? "mark as sent" : action}: ${e.message}`)
    } finally {
      setBusy("")
    }
  }

  const tile = (label, value, sub, color) => (
    <div style={{ ...card, marginBottom: 0 }}>
      <p style={{ margin: 0, fontSize: "0.8rem", color: "#6f6f6f" }}>{label}</p>
      <p style={{ margin: "0.25rem 0 0", fontSize: "1.6rem", fontWeight: 700, color }}>{value}</p>
      {sub && <p style={{ margin: 0, fontSize: "0.75rem", color: "#8a8a8a" }}>{sub}</p>}
    </div>
  )

  const redemptions = (data?.redemptions || []).filter((r) => (filter === "toSend" ? !r.fulfilledAt && !r.onHold : filter === "held" ? !r.fulfilledAt && r.onHold : filter === "sent" ? r.fulfilledAt : true))

  return (
    <div style={{ padding: embedded ? 0 : "1.5rem", maxWidth: "1200px" }}>
      {!embedded && <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Rewards & Points</h1>}
      {!embedded && (
        <p style={{ margin: "0.25rem 0 1.25rem", color: "#6f6f6f", fontSize: "0.875rem" }}>
          Live from the SurveyFieldwork Panel. 100 points = ₹10 / £1 / $1.
        </p>
      )}

      {error && <div style={{ ...card, color: "#b91c1c" }}>{error}</div>}
      {!data && !error && <div style={card}>Loading…</div>}

      {data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "0.75rem", marginBottom: "1.25rem" }}>
            {tile("Gift cards to send", n(data.totals.toSend), "redeemed, not yet marked sent", data.totals.toSend ? "#dc2626" : "#15803d")}
            {tile("On hold for review", n(data.totals.onHold), "release or keep holding", data.totals.onHold ? "#d97706" : "#15803d")}
            {tile("Points earned", n(data.totals.earnedPoints), "credited to balances", "#166534")}
            {tile("Points on hold", n(data.totals.onHoldPoints), "released when the profile is complete", "#d97706")}
            {tile("Points redeemed", n(data.totals.redeemedPoints), "as gift cards", "#e8910a")}
            {tile("Points in balances", n(data.totals.balancePoints), "owed to members if redeemed", "#1f2937")}
          </div>

          <div style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
              <h3 style={{ margin: 0, fontSize: "1rem" }}>Gift-card redemptions</h3>
              <div style={{ display: "flex", gap: "0.25rem", background: "#f5f3ef", borderRadius: "8px", padding: "0.2rem" }}>
                {[["toSend", "To send"], ["held", "On hold"], ["sent", "Sent"], ["all", "All"]].map(([k, label]) => (
                  <button key={k} type="button" onClick={() => setFilter(k)}
                    style={{ border: "none", borderRadius: "6px", padding: "0.3rem 0.75rem", fontSize: "0.8rem", cursor: "pointer", background: filter === k ? "#fff" : "transparent", fontWeight: filter === k ? 600 : 400 }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {redemptions.length === 0 ? (
              <p style={{ color: "#6f6f6f", fontSize: "0.875rem", margin: 0 }}>{filter === "toSend" ? "Nothing to send — all redemptions are done." : "No redemptions."}</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr><th style={th}>Requested</th><th style={th}>Member</th><th style={th}>Country</th><th style={th}>Gift card</th><th style={th}>Points</th><th style={th}>Status</th></tr>
                  </thead>
                  <tbody>
                    {redemptions.map((r) => (
                      <tr key={r.id}>
                        <td style={{ ...td, whiteSpace: "nowrap" }}>{new Date(r.at).toLocaleString()}</td>
                        <td style={td}>{r.name || "—"}<div style={{ fontSize: "0.75rem", color: "#6f6f6f" }}>{r.email} · {r.panelistId}</div></td>
                        <td style={td}>{COUNTRY_LABELS[r.country] || r.country || "—"}</td>
                        <td style={{ ...td, fontWeight: 700 }}>{r.giftCard}</td>
                        <td style={td}>{n(r.points)}</td>
                        <td style={td}>
                          {r.fulfilledAt ? (
                            <span style={{ color: "#15803d" }}>Sent {new Date(r.fulfilledAt).toLocaleDateString()}{r.fulfilledBy ? ` · ${r.fulfilledBy}` : ""}</span>
                          ) : r.onHold ? (
                            <div>
                              <span style={{ color: "#d97706", fontWeight: 600 }}>On hold{r.suspended ? " · member suspended" : ""}</span>
                              <ul style={{ margin: "0.25rem 0 0.4rem", paddingLeft: "1rem", fontSize: "0.75rem", color: "#6f6f6f" }}>
                                {r.holdReasons.map((h) => <li key={h}>{h}</li>)}
                              </ul>
                              {!r.suspended && (
                                <button type="button" style={{ ...btn, background: "#fff", color: "#a15f06" }} disabled={busy === r.id} onClick={() => act(r, "release")}>{busy === r.id ? "Saving…" : "Release"}</button>
                              )}
                            </div>
                          ) : (
                            <div style={{ display: "flex", gap: "0.4rem" }}>
                              <button type="button" style={btn} disabled={busy === r.id} onClick={() => act(r, "sent")}>{busy === r.id ? "Saving…" : "Mark sent"}</button>
                              <button type="button" style={{ ...btn, background: "#fff", color: "#d97706", borderColor: "#d97706" }} disabled={busy === r.id} onClick={() => act(r, "hold")}>Hold</button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div style={card}>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem" }}>Points by reason</h3>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr><th style={th}>Reason</th><th style={th}>Awards</th><th style={th}>Points earned</th><th style={th}>Points on hold</th></tr></thead>
              <tbody>
                {data.byType.map((t) => (
                  <tr key={t.label}><td style={td}>{t.label}</td><td style={td}>{n(t.awards)}</td><td style={td}>{n(t.earnedPoints)}</td><td style={td}>{n(t.onHoldPoints)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

export default RewardsPoints
