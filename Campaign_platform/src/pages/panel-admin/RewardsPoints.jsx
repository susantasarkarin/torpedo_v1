import { useCallback, useEffect, useState } from "react"
import { buildApiUrl } from "../../config"
import { authFetch } from "../../utils/api"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

/**
 * Rewards & Points — live from the SurveyFieldwork Panel: points members have
 * earned, points on hold (profile not complete yet), redemptions, and the
 * Amazon gift cards still to be sent.
 */

const card = { background: "#fff", border: "1px solid #e5e7eb", borderRadius: "10px", padding: "1.25rem", marginBottom: "1.25rem" }
const th = { textAlign: "left", padding: "0.5rem 0.6rem", fontSize: "0.8rem", color: "#4b5563", borderBottom: "1px solid #e5e7eb", whiteSpace: "nowrap" }
const td = { padding: "0.5rem 0.6rem", fontSize: "0.875rem", color: "#1a1a1a", borderBottom: "1px solid #f3f4f6" }
const btn = { padding: "0.35rem 0.75rem", borderRadius: "6px", border: "1px solid #4f46e5", background: "#4f46e5", color: "#fff", cursor: "pointer", fontSize: "0.8rem" }
const COUNTRY_LABELS = { IN: "India", UK: "United Kingdom", GB: "United Kingdom", US: "United States" }
const n = (v) => (v || 0).toLocaleString()

function RewardsPoints() {
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

  const markSent = async (r) => {
    if (!window.confirm(`Mark the ${r.giftCard} gift card for ${r.name || r.email} as sent?`)) return
    setBusy(r.id)
    try {
      const res = await authFetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/panel-redemptions/${r.id}/sent`), {
        method: "POST",
        headers: { Authorization: localStorage.getItem("session_id") },
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      await load()
    } catch (e) {
      alert(`Could not mark as sent: ${e.message}`)
    } finally {
      setBusy("")
    }
  }

  const tile = (label, value, sub, color) => (
    <div style={{ ...card, marginBottom: 0 }}>
      <p style={{ margin: 0, fontSize: "0.8rem", color: "#6b7280" }}>{label}</p>
      <p style={{ margin: "0.25rem 0 0", fontSize: "1.6rem", fontWeight: 700, color }}>{value}</p>
      {sub && <p style={{ margin: 0, fontSize: "0.75rem", color: "#9ca3af" }}>{sub}</p>}
    </div>
  )

  const redemptions = (data?.redemptions || []).filter((r) => (filter === "toSend" ? !r.fulfilledAt : filter === "sent" ? r.fulfilledAt : true))

  return (
    <div style={{ padding: "1.5rem", maxWidth: "1200px" }}>
      <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Rewards & Points</h1>
      <p style={{ margin: "0.25rem 0 1.25rem", color: "#6b7280", fontSize: "0.875rem" }}>
        Live from the SurveyFieldwork Panel. 100 points = ₹10 / £1 / $1.
      </p>

      {error && <div style={{ ...card, color: "#b91c1c" }}>{error}</div>}
      {!data && !error && <div style={card}>Loading…</div>}

      {data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "0.75rem", marginBottom: "1.25rem" }}>
            {tile("Gift cards to send", n(data.totals.toSend), "redeemed, not yet marked sent", data.totals.toSend ? "#dc2626" : "#059669")}
            {tile("Points earned", n(data.totals.earnedPoints), "credited to balances", "#047857")}
            {tile("Points on hold", n(data.totals.onHoldPoints), "released when the profile is complete", "#d97706")}
            {tile("Points redeemed", n(data.totals.redeemedPoints), "as gift cards", "#4f46e5")}
            {tile("Points in balances", n(data.totals.balancePoints), "owed to members if redeemed", "#1f2937")}
          </div>

          <div style={card}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
              <h3 style={{ margin: 0, fontSize: "1rem" }}>Gift-card redemptions</h3>
              <div style={{ display: "flex", gap: "0.25rem", background: "#f3f4f6", borderRadius: "8px", padding: "0.2rem" }}>
                {[["toSend", "To send"], ["sent", "Sent"], ["all", "All"]].map(([k, label]) => (
                  <button key={k} type="button" onClick={() => setFilter(k)}
                    style={{ border: "none", borderRadius: "6px", padding: "0.3rem 0.75rem", fontSize: "0.8rem", cursor: "pointer", background: filter === k ? "#fff" : "transparent", fontWeight: filter === k ? 600 : 400 }}>
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {redemptions.length === 0 ? (
              <p style={{ color: "#6b7280", fontSize: "0.875rem", margin: 0 }}>{filter === "toSend" ? "Nothing to send — all redemptions are done." : "No redemptions."}</p>
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
                        <td style={td}>{r.name || "—"}<div style={{ fontSize: "0.75rem", color: "#6b7280" }}>{r.email} · {r.panelistId}</div></td>
                        <td style={td}>{COUNTRY_LABELS[r.country] || r.country || "—"}</td>
                        <td style={{ ...td, fontWeight: 700 }}>{r.giftCard}</td>
                        <td style={td}>{n(r.points)}</td>
                        <td style={td}>
                          {r.fulfilledAt ? (
                            <span style={{ color: "#059669" }}>Sent {new Date(r.fulfilledAt).toLocaleDateString()}{r.fulfilledBy ? ` · ${r.fulfilledBy}` : ""}</span>
                          ) : (
                            <button type="button" style={btn} disabled={busy === r.id} onClick={() => markSent(r)}>{busy === r.id ? "Saving…" : "Mark sent"}</button>
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
