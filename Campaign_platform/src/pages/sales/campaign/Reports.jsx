import { useState, useEffect } from "react"
import { buildApiUrl } from "../../../config"

function AUTH() {
  const s = localStorage.getItem("session_id")
  return s ? { Authorization: s } : {}
}

function Reports() {
  const [campaigns, setCampaigns] = useState([])
  const [selectedId, setSelectedId] = useState("")
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [loadingCampaigns, setLoadingCampaigns] = useState(true)

  // Load campaign list on mount
  useEffect(() => {
    setLoadingCampaigns(true)
    fetch(buildApiUrl("/api/cold-outreach/campaigns"), { headers: AUTH() })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        const list = d?.campaigns || []
        setCampaigns(list)
        if (list.length > 0) setSelectedId(list[0].campaign_id)
      })
      .finally(() => setLoadingCampaigns(false))
  }, [])

  // Load stats when campaign changes
  useEffect(() => {
    if (!selectedId) { setStats(null); return }
    setLoading(true)
    fetch(buildApiUrl(`/api/cold-outreach/campaigns/${selectedId}/stats`), { headers: AUTH() })
      .then(r => r.ok ? r.json() : null)
      .then(d => setStats(d))
      .finally(() => setLoading(false))
  }, [selectedId])

  const o = stats?.overall || {}
  const steps = stats?.by_step || []

  return (
    <div style={{ padding: "1.5rem", maxWidth: 960 }}>
      <h2 style={{ color: "#f1f5f9", fontSize: "1.25rem", marginBottom: "1rem" }}>Campaign Reports</h2>

      {/* Campaign selector */}
      {loadingCampaigns ? (
        <p style={{ color: "#94a3b8" }}>Loading campaigns...</p>
      ) : campaigns.length === 0 ? (
        <p style={{ color: "#94a3b8" }}>No campaigns found.</p>
      ) : (
        <select
          value={selectedId}
          onChange={e => setSelectedId(e.target.value)}
          style={{
            background: "#1e293b", color: "#f1f5f9", border: "1px solid #334155",
            borderRadius: 8, padding: "8px 12px", fontSize: "0.9rem", marginBottom: "1.25rem", width: "100%"
          }}
        >
          {campaigns.map(c => (
            <option key={c.campaign_id} value={c.campaign_id}>
              {c.name || c.campaign_id} — {c.business || ""} ({c.stats?.sent || 0} sent)
            </option>
          ))}
        </select>
      )}

      {loading && <p style={{ color: "#94a3b8" }}>Loading stats...</p>}

      {!loading && stats && (
        <>
          {/* Overall KPI cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 14, marginBottom: 24 }}>
            {[
              ["Enrolled", o.enrolled, "#3b82f6"],
              ["Sent", o.total_sent, "#6366f1"],
              ["Open Rate", o.open_rate != null ? `${o.open_rate}%` : "—", "#22c55e"],
              ["Reply Rate", o.reply_rate != null ? `${o.reply_rate}%` : "—", "#f59e0b"],
              ["Bounce Rate", o.bounce_rate != null ? `${o.bounce_rate}%` : "—", "#ef4444"],
            ].map(([label, val, accent]) => (
              <div key={label} style={{
                background: "#1e293b", borderRadius: 10, padding: "16px 12px", textAlign: "center",
                border: "1px solid #334155"
              }}>
                <div style={{ fontWeight: 700, fontSize: "1.4rem", color: accent }}>{val ?? "—"}</div>
                <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginTop: 4 }}>{label}</div>
              </div>
            ))}
          </div>

          {/* Absolute counts */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 24 }}>
            {[
              ["Opened", o.total_opened],
              ["Replied", o.total_replied],
              ["Bounced", o.total_bounced],
              ["Unsubscribed", o.total_unsubscribed],
            ].map(([label, val]) => (
              <div key={label} style={{
                background: "#0f172a", borderRadius: 8, padding: "12px", textAlign: "center",
                border: "1px solid #1e293b"
              }}>
                <div style={{ fontWeight: 600, fontSize: "1.1rem", color: "#e2e8f0" }}>{val ?? 0}</div>
                <div style={{ fontSize: "0.7rem", color: "#64748b", marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </div>

          {/* Per-step breakdown table */}
          <h3 style={{ color: "#e2e8f0", fontSize: "1rem", marginBottom: 10 }}>Per-Step Breakdown</h3>
          {steps.length === 0 ? (
            <p style={{ color: "#64748b", fontSize: "0.85rem" }}>No sends yet for this campaign.</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #334155" }}>
                  {["Step", "Day", "Sent", "Opened", "Replied", "Bounced", "Open %", "Reply %"].map(h => (
                    <th key={h} style={{ padding: "8px 10px", textAlign: "left", color: "#94a3b8", fontWeight: 600 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {steps.map(s => (
                  <tr key={s.step_number} style={{ borderBottom: "1px solid #1e293b" }}>
                    <td style={{ padding: "8px 10px", color: "#f1f5f9" }}>{s.step_number}</td>
                    <td style={{ padding: "8px 10px", color: "#94a3b8" }}>Day {(s.day_offset || 0) + 1}</td>
                    <td style={{ padding: "8px 10px", color: "#e2e8f0" }}>{s.sent}</td>
                    <td style={{ padding: "8px 10px", color: "#22c55e" }}>{s.opened}</td>
                    <td style={{ padding: "8px 10px", color: "#f59e0b" }}>{s.replied}</td>
                    <td style={{ padding: "8px 10px", color: "#ef4444" }}>{s.bounced}</td>
                    <td style={{ padding: "8px 10px", color: "#94a3b8" }}>{s.open_rate}%</td>
                    <td style={{ padding: "8px 10px", color: "#94a3b8" }}>{s.reply_rate}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  )
}

export default Reports