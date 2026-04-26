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
  const [trendDays, setTrendDays] = useState(30)
  const [trendLoading, setTrendLoading] = useState(false)
  const [trendData, setTrendData] = useState(null)
  const [liDays, setLiDays] = useState(30)
  const [liLoading, setLiLoading] = useState(false)
  const [liDashboard, setLiDashboard] = useState(null)
  const [liRecent, setLiRecent] = useState([])
  const [liUpdatingId, setLiUpdatingId] = useState("")
  const [liError, setLiError] = useState("")
  const [liRowNotice, setLiRowNotice] = useState({})

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

  useEffect(() => {
    setTrendLoading(true)
    fetch(buildApiUrl(`/api/cold-outreach/reports/divisions-over-time?days=${trendDays}`), { headers: AUTH() })
      .then(r => r.ok ? r.json() : null)
      .then(d => setTrendData(d))
      .finally(() => setTrendLoading(false))
  }, [trendDays])

  const loadLinkedInOpportunities = () => {
    setLiLoading(true)
    setLiError("")
    Promise.all([
      fetch(buildApiUrl(`/api/marketing/linkedin/opportunities/dashboard?days=${liDays}`), { headers: AUTH() })
        .then(r => r.ok ? r.json() : null),
      fetch(buildApiUrl(`/api/marketing/linkedin/opportunities?days=${liDays}&limit=8`), { headers: AUTH() })
        .then(r => r.ok ? r.json() : []),
    ])
      .then(([dash, items]) => {
        setLiDashboard(dash)
        setLiRecent(Array.isArray(items) ? items : [])
      })
      .catch(() => {
        setLiError("Failed to load LinkedIn opportunities.")
      })
      .finally(() => setLiLoading(false))
  }

  useEffect(() => {
    loadLinkedInOpportunities()
  }, [liDays])

  const moveOpportunityStatus = async (opportunityId, status, isUndo = false) => {
    if (!opportunityId || !status) return
    const previousStatus = (liRecent.find((item) => item._id === opportunityId)?.status || "discovered").toLowerCase()
    setLiUpdatingId(opportunityId)
    setLiError("")
    try {
      const r = await fetch(buildApiUrl(`/api/marketing/linkedin/opportunities/${opportunityId}`), {
        method: "PATCH",
        headers: { ...AUTH(), "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      })
      if (!r.ok) throw new Error("status update failed")

      setLiRecent((curr) => curr.map((item) => (
        item._id === opportunityId ? { ...item, status } : item
      )))

      if (isUndo) {
        setLiRowNotice((curr) => ({
          ...curr,
          [opportunityId]: { type: "ok", text: "Undone" },
        }))
      } else {
        setLiRowNotice((curr) => ({
          ...curr,
          [opportunityId]: {
            type: "ok",
            text: "Saved",
            undoFrom: previousStatus,
          },
        }))
      }

      setTimeout(() => {
        setLiRowNotice((curr) => {
          const next = { ...curr }
          delete next[opportunityId]
          return next
        })
      }, 1800)

      loadLinkedInOpportunities()
    } catch (_) {
      setLiError("Failed to update opportunity status.")
      setLiRowNotice((curr) => ({
        ...curr,
        [opportunityId]: { type: "err", text: "Retry" },
      }))
    } finally {
      setLiUpdatingId("")
    }
  }

  const undoOpportunityStatus = (opportunityId) => {
    const fromStatus = liRowNotice[opportunityId]?.undoFrom
    if (!fromStatus) return
    moveOpportunityStatus(opportunityId, fromStatus, true)
  }

  const quickStatusActions = (status) => {
    const current = (status || "discovered").toLowerCase()
    if (current === "discovered") return [{ label: "Qualify", value: "qualified", color: "#22c55e" }]
    if (current === "qualified") return [{ label: "Contact", value: "contacted", color: "#f59e0b" }]
    if (current === "contacted") return [{ label: "Mark Replied", value: "replied", color: "#34d399" }]
    if (current === "replied") return [{ label: "Convert", value: "converted", color: "#f97316" }]
    return []
  }

  const statusColors = (status) => {
    const s = (status || "").toLowerCase()
    if (s === "converted") return { fg: "#fdba74", bd: "#f97316" }
    if (s === "replied") return { fg: "#6ee7b7", bd: "#10b981" }
    if (s === "contacted") return { fg: "#fcd34d", bd: "#f59e0b" }
    if (s === "qualified") return { fg: "#86efac", bd: "#22c55e" }
    if (s === "dismissed") return { fg: "#fca5a5", bd: "#ef4444" }
    return { fg: "#93c5fd", bd: "#3b82f6" }
  }

  const o = stats?.overall || {}
  const steps = stats?.by_step || []
  const t = trendData?.totals || {}
  const leadSources = trendData?.lead_source_totals || {}
  const divisionTotals = trendData?.division_totals || {}
  const dailyRows = trendData?.daily || []
  const liStatus = liDashboard?.status_totals || {}
  const liDivisionTotals = liDashboard?.division_totals || {}

  const topSources = Object.entries(leadSources)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)

  return (
    <div style={{ padding: "1.5rem", maxWidth: 960 }}>
      <h2 style={{ color: "#f1f5f9", fontSize: "1.25rem", marginBottom: "1rem" }}>Campaign Reports</h2>

      <div style={{
        background: "#111827",
        border: "1px solid #334155",
        borderRadius: 12,
        padding: "1rem",
        marginBottom: "1.25rem",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem", gap: 12, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0, color: "#e2e8f0", fontSize: "1rem" }}>
            All Divisions Trend
          </h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: "#94a3b8", fontSize: "0.8rem" }}>Window</span>
            <select
              value={trendDays}
              onChange={(e) => setTrendDays(Number(e.target.value))}
              style={{
                background: "#1e293b",
                color: "#f1f5f9",
                border: "1px solid #334155",
                borderRadius: 8,
                padding: "6px 10px",
                fontSize: "0.8rem",
              }}
            >
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={60}>Last 60 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </div>
        </div>

        {trendLoading ? (
          <p style={{ color: "#94a3b8", margin: 0 }}>Loading trend data...</p>
        ) : !trendData ? (
          <p style={{ color: "#94a3b8", margin: 0 }}>No trend data available.</p>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 10, marginBottom: 12 }}>
              {[
                ["Leads Generated", t.leads_generated ?? 0, "#38bdf8"],
                ["Mails Sent", t.mails_sent ?? 0, "#818cf8"],
                ["Opened", t.opened ?? 0, "#22c55e"],
                ["Replied", t.replied ?? 0, "#f59e0b"],
                ["Bounced", t.bounced ?? 0, "#ef4444"],
              ].map(([label, val, color]) => (
                <div key={label} style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, padding: "10px", textAlign: "center" }}>
                  <div style={{ color, fontWeight: 700, fontSize: "1.1rem" }}>{val}</div>
                  <div style={{ color: "#94a3b8", fontSize: "0.72rem", marginTop: 2 }}>{label}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 12, marginBottom: 10 }}>
              <div style={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 8, padding: 10 }}>
                <div style={{ color: "#cbd5e1", fontSize: "0.8rem", marginBottom: 8, fontWeight: 600 }}>Leads by Source (Media)</div>
                {topSources.length === 0 ? (
                  <div style={{ color: "#64748b", fontSize: "0.78rem" }}>No lead source data yet.</div>
                ) : (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {topSources.map(([src, count]) => (
                      <span key={src} style={{
                        background: "#1e293b",
                        border: "1px solid #334155",
                        color: "#e2e8f0",
                        borderRadius: 999,
                        padding: "4px 10px",
                        fontSize: "0.72rem",
                      }}>
                        {src}: {count}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div style={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 8, padding: 10 }}>
                <div style={{ color: "#cbd5e1", fontSize: "0.8rem", marginBottom: 8, fontWeight: 600 }}>Division Email Performance</div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.72rem" }}>
                  <thead>
                    <tr>
                      {[
                        "Division", "Sent", "Open%", "Reply%", "Bounce%",
                      ].map(h => (
                        <th key={h} style={{ textAlign: "left", color: "#94a3b8", padding: "4px 4px", borderBottom: "1px solid #1e293b" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(divisionTotals).map(([biz, v]) => (
                      <tr key={biz}>
                        <td style={{ color: "#e2e8f0", padding: "4px 4px", textTransform: "uppercase" }}>{biz}</td>
                        <td style={{ color: "#e2e8f0", padding: "4px 4px" }}>{v.mails_sent ?? 0}</td>
                        <td style={{ color: "#22c55e", padding: "4px 4px" }}>{v.open_rate ?? 0}%</td>
                        <td style={{ color: "#f59e0b", padding: "4px 4px" }}>{v.reply_rate ?? 0}%</td>
                        <td style={{ color: "#ef4444", padding: "4px 4px" }}>{v.bounce_rate ?? 0}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div style={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 8, padding: 10 }}>
              <div style={{ color: "#cbd5e1", fontSize: "0.8rem", marginBottom: 8, fontWeight: 600 }}>Daily Trend</div>
              <div style={{ maxHeight: 240, overflow: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.72rem" }}>
                  <thead>
                    <tr>
                      {["Date", "Leads", "Sent", "Opened", "Replied", "Bounced"].map(h => (
                        <th key={h} style={{ textAlign: "left", color: "#94a3b8", padding: "5px 6px", borderBottom: "1px solid #1e293b" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dailyRows.map((r) => (
                      <tr key={r.date} style={{ borderBottom: "1px solid #111827" }}>
                        <td style={{ color: "#cbd5e1", padding: "5px 6px" }}>{r.date}</td>
                        <td style={{ color: "#38bdf8", padding: "5px 6px" }}>{r.leads_generated}</td>
                        <td style={{ color: "#818cf8", padding: "5px 6px" }}>{r.mails_sent}</td>
                        <td style={{ color: "#22c55e", padding: "5px 6px" }}>{r.opened}</td>
                        <td style={{ color: "#f59e0b", padding: "5px 6px" }}>{r.replied}</td>
                        <td style={{ color: "#ef4444", padding: "5px 6px" }}>{r.bounced}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>

      <div style={{
        background: "#111827",
        border: "1px solid #334155",
        borderRadius: 12,
        padding: "1rem",
        marginBottom: "1.25rem",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.75rem", gap: 12, flexWrap: "wrap" }}>
          <h3 style={{ margin: 0, color: "#e2e8f0", fontSize: "1rem" }}>
            LinkedIn Opportunities
          </h3>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ color: "#94a3b8", fontSize: "0.8rem" }}>Window</span>
            <select
              value={liDays}
              onChange={(e) => setLiDays(Number(e.target.value))}
              style={{
                background: "#1e293b",
                color: "#f1f5f9",
                border: "1px solid #334155",
                borderRadius: 8,
                padding: "6px 10px",
                fontSize: "0.8rem",
              }}
            >
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={60}>Last 60 days</option>
              <option value={90}>Last 90 days</option>
            </select>
          </div>
        </div>

        {liLoading ? (
          <p style={{ color: "#94a3b8", margin: 0 }}>Loading LinkedIn opportunity data...</p>
        ) : !liDashboard ? (
          <p style={{ color: "#94a3b8", margin: 0 }}>No LinkedIn opportunity data available.</p>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 10, marginBottom: 12 }}>
              {[
                ["Total", liDashboard.total ?? 0, "#38bdf8"],
                ["Discovered", liStatus.discovered ?? 0, "#818cf8"],
                ["Qualified", liStatus.qualified ?? 0, "#22c55e"],
                ["Contacted", liStatus.contacted ?? 0, "#f59e0b"],
                ["Replied", liStatus.replied ?? 0, "#34d399"],
                ["Converted", liStatus.converted ?? 0, "#f97316"],
              ].map(([label, val, color]) => (
                <div key={label} style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: 8, padding: "10px", textAlign: "center" }}>
                  <div style={{ color, fontWeight: 700, fontSize: "1.1rem" }}>{val}</div>
                  <div style={{ color: "#94a3b8", fontSize: "0.72rem", marginTop: 2 }}>{label}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 12 }}>
              <div style={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 8, padding: 10 }}>
                <div style={{ color: "#cbd5e1", fontSize: "0.8rem", marginBottom: 8, fontWeight: 600 }}>Opportunity Routing by Division</div>
                {Object.keys(liDivisionTotals).length === 0 ? (
                  <div style={{ color: "#64748b", fontSize: "0.78rem" }}>No division routing data yet.</div>
                ) : (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {Object.entries(liDivisionTotals).map(([division, count]) => (
                      <span key={division} style={{
                        background: "#1e293b",
                        border: "1px solid #334155",
                        color: "#e2e8f0",
                        borderRadius: 999,
                        padding: "4px 10px",
                        fontSize: "0.72rem",
                        textTransform: "uppercase",
                      }}>
                        {division}: {count}
                      </span>
                    ))}
                  </div>
                )}
                <div style={{ marginTop: 10, color: "#64748b", fontSize: "0.72rem" }}>
                  Avg confidence: {liDashboard.avg_confidence ?? 0}
                </div>
              </div>

              <div style={{ background: "#0b1220", border: "1px solid #1e293b", borderRadius: 8, padding: 10 }}>
                <div style={{ color: "#cbd5e1", fontSize: "0.8rem", marginBottom: 8, fontWeight: 600 }}>Recent Opportunities</div>
                {liError && (
                  <div style={{ color: "#fca5a5", fontSize: "0.75rem", marginBottom: 8 }}>{liError}</div>
                )}
                {liRecent.length === 0 ? (
                  <div style={{ color: "#64748b", fontSize: "0.78rem" }}>No opportunities in this time window.</div>
                ) : (
                  <div style={{ maxHeight: 220, overflow: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.72rem" }}>
                      <thead>
                        <tr>
                          {["Sender", "Company", "Status", "Division", "Score", "Actions", "Move To"].map(h => (
                            <th key={h} style={{ textAlign: "left", color: "#94a3b8", padding: "5px 6px", borderBottom: "1px solid #1e293b" }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {liRecent.map((r) => (
                          <tr key={r._id} style={{ borderBottom: "1px solid #111827" }}>
                            <td style={{ color: "#e2e8f0", padding: "5px 6px" }}>{r.sender_name || "-"}</td>
                            <td style={{ color: "#cbd5e1", padding: "5px 6px" }}>{r.sender_company || "-"}</td>
                            <td style={{ padding: "5px 6px" }}>
                              <span style={{
                                display: "inline-block",
                                textTransform: "capitalize",
                                color: statusColors(r.status).fg,
                                border: `1px solid ${statusColors(r.status).bd}`,
                                borderRadius: 999,
                                padding: "2px 8px",
                                fontSize: "0.66rem",
                                letterSpacing: 0.2,
                              }}>
                                {r.status || "-"}
                              </span>
                            </td>
                            <td style={{ color: "#f1f5f9", padding: "5px 6px", textTransform: "uppercase" }}>{r.division_owner || "-"}</td>
                            <td style={{ color: "#38bdf8", padding: "5px 6px" }}>{r.intent_score ?? 0}</td>
                            <td style={{ padding: "5px 6px" }}>
                              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                {quickStatusActions(r.status).map((action) => (
                                  <button
                                    key={action.value}
                                    type="button"
                                    disabled={liUpdatingId === r._id}
                                    onClick={() => moveOpportunityStatus(r._id, action.value)}
                                    style={{
                                      background: "#0f172a",
                                      color: action.color,
                                      border: `1px solid ${action.color}`,
                                      borderRadius: 999,
                                      padding: "2px 8px",
                                      fontSize: "0.66rem",
                                      cursor: liUpdatingId === r._id ? "not-allowed" : "pointer",
                                      opacity: liUpdatingId === r._id ? 0.65 : 1,
                                    }}
                                  >
                                    {action.label}
                                  </button>
                                ))}
                                {(r.status || "").toLowerCase() !== "dismissed" && (
                                  <button
                                    type="button"
                                    disabled={liUpdatingId === r._id}
                                    onClick={() => moveOpportunityStatus(r._id, "dismissed")}
                                    style={{
                                      background: "#0f172a",
                                      color: "#fca5a5",
                                      border: "1px solid #ef4444",
                                      borderRadius: 999,
                                      padding: "2px 8px",
                                      fontSize: "0.66rem",
                                      cursor: liUpdatingId === r._id ? "not-allowed" : "pointer",
                                      opacity: liUpdatingId === r._id ? 0.65 : 1,
                                    }}
                                  >
                                    Dismiss
                                  </button>
                                )}
                              </div>
                            </td>
                            <td style={{ padding: "5px 6px" }}>
                              <select
                                value={r.status || "discovered"}
                                disabled={liUpdatingId === r._id}
                                onChange={(e) => moveOpportunityStatus(r._id, e.target.value)}
                                style={{
                                  background: "#111827",
                                  color: "#e2e8f0",
                                  border: "1px solid #334155",
                                  borderRadius: 6,
                                  padding: "2px 6px",
                                  fontSize: "0.7rem",
                                }}
                              >
                                {["discovered", "qualified", "contacted", "replied", "converted", "dismissed"].map(status => (
                                  <option key={status} value={status}>{status}</option>
                                ))}
                              </select>
                              <span style={{
                                marginLeft: 8,
                                color: liRowNotice[r._id]?.type === "ok" ? "#86efac" : "#fca5a5",
                                fontSize: "0.66rem",
                                opacity: liRowNotice[r._id] ? 1 : 0,
                                transition: "opacity 180ms ease",
                                display: "inline-flex",
                                alignItems: "center",
                                gap: 6,
                              }}>
                                {liRowNotice[r._id]?.text || ""}
                                {!!liRowNotice[r._id]?.undoFrom && liUpdatingId !== r._id && (
                                  <button
                                    type="button"
                                    onClick={() => undoOpportunityStatus(r._id)}
                                    style={{
                                      background: "transparent",
                                      color: "#93c5fd",
                                      border: "1px solid #3b82f6",
                                      borderRadius: 999,
                                      padding: "1px 7px",
                                      fontSize: "0.62rem",
                                      cursor: "pointer",
                                    }}
                                  >
                                    Undo
                                  </button>
                                )}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </div>

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