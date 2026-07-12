import { useState, useEffect } from "react"
import { buildApiUrl } from "../../config"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

const COUNTRY_NAMES = {
  US: "United States", IN: "India", GB: "United Kingdom", AU: "Australia",
  CA: "Canada", DE: "Germany", FR: "France", SG: "Singapore", AE: "UAE",
  XX: "Unknown",
}
function countryName(cc) { return COUNTRY_NAMES[cc] || cc }

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{ padding: "1.5rem", border: "1px solid #e5e7eb", borderRadius: "12px", backgroundColor: "#f9fafb" }}>
      <p style={{ fontSize: "0.875rem", color: "#6b7280", fontWeight: "600", marginBottom: "0.5rem" }}>{label}</p>
      <p style={{ fontSize: "2rem", fontWeight: "700", color: color || "#059669", marginBottom: "0.25rem" }}>{value}</p>
      {sub && <p style={{ fontSize: "0.8rem", color: "#9ca3af" }}>{sub}</p>}
    </div>
  )
}

function PanelDashboard() {
  const [dailyStats, setDailyStats] = useState([])
  const [dailyLoading, setDailyLoading] = useState(false)
  const [registrationStats, setRegistrationStats] = useState({})
  const [registrationLoading, setRegistrationLoading] = useState(false)
  const [totalSent, setTotalSent] = useState(0)
  const [totalBounced, setTotalBounced] = useState(0)
  const [totalConfirmed, setTotalConfirmed] = useState(0)
  const [days, setDays] = useState(30)

  // SFW Panel
  const [sfwOverview, setSfwOverview] = useState(null)
  const [sfwCountries, setSfwCountries] = useState([])
  const [sfwLoading, setSfwLoading] = useState(false)

  useEffect(() => {
    fetchDailyStats()
    fetchRegistrationStats()
  }, [days])

  useEffect(() => {
    fetchSfwPanelData()
  }, [])

  const fetchDailyStats = async () => {
    setDailyLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/dashboard/daily-stats?days=${days}`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setDailyStats(data.daily_stats || [])
        setTotalSent(data.total_sent || 0)
        setTotalBounced(data.total_bounced || 0)
        setTotalConfirmed(data.total_confirmed || 0)
      }
    } catch (err) {
      console.error("Failed to fetch daily stats:", err)
    } finally {
      setDailyLoading(false)
    }
  }

  const fetchRegistrationStats = async () => {
    setRegistrationLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/dashboard/registrations-by-country`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setRegistrationStats(data.registrations_by_country || {})
      }
    } catch (err) {
      console.error("Failed to fetch registration stats:", err)
    } finally {
      setRegistrationLoading(false)
    }
  }

  const fetchSfwPanelData = async () => {
    setSfwLoading(true)
    const sessionId = localStorage.getItem("session_id")
    try {
      const [ovRes, ctRes] = await Promise.all([
        fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/dashboard/sfwpanel-overview`), { headers: { Authorization: sessionId } }),
        fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/dashboard/sfwpanel-countries`), { headers: { Authorization: sessionId } }),
      ])
      if (ovRes.ok) setSfwOverview(await ovRes.json())
      if (ctRes.ok) { const d = await ctRes.json(); setSfwCountries(d.countries || []) }
    } catch (err) {
      console.error("Failed to fetch SFW panel data:", err)
    } finally {
      setSfwLoading(false)
    }
  }

  const maxDailyCount = dailyStats.length > 0 ? Math.max(...dailyStats.map(d => d.count || 0)) : 0
  const chartHeight = 300
  const sortedCountries = Object.entries(registrationStats).sort((a, b) => b[1] - a[1]).slice(0, 15)
  const sfwTotal = sfwCountries.reduce((s, c) => s + c.total, 0)

  return (
    <div>
      {/* ── Existing email campaign dashboard ─────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Panel Dashboard</h2>
            <p className="card-description">Monitor email sending activity and panelist registrations</p>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
          <StatCard label="Total Sent" value={totalSent.toLocaleString()} sub="All-time invitations sent" color="#059669" />
          <StatCard label="Confirmed" value={totalConfirmed.toLocaleString()} sub="Double opt-in completed" color="#0284c7" />
          <StatCard label="Bounced" value={totalBounced.toLocaleString()} sub="Failed delivery" color="#dc2626" />
          <StatCard label="Conversion Rate" value={`${totalSent > 0 ? ((totalConfirmed / totalSent) * 100).toFixed(1) : 0}%`} sub="Confirmed / Total sent" color="#7c3aed" />
        </div>

        <div style={{ marginBottom: "2rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h3 style={{ fontSize: "1.125rem", fontWeight: "700", color: "#111827" }}>Daily Email Activity</h3>
            <select value={days} onChange={(e) => setDays(parseInt(e.target.value))}
              style={{ padding: "0.5rem 0.75rem", border: "1px solid #d1d5db", borderRadius: "6px", fontSize: "0.875rem", backgroundColor: "#fff" }}>
              <option value={7}>Last 7 days</option>
              <option value={14}>Last 14 days</option>
              <option value={30}>Last 30 days</option>
              <option value={60}>Last 60 days</option>
            </select>
          </div>
          {dailyLoading ? (
            <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem 0" }}>Loading daily statistics...</p>
          ) : dailyStats.length === 0 ? (
            <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem 0" }}>No data available</p>
          ) : (
            <div style={{ border: "1px solid #e5e7eb", borderRadius: "12px", padding: "1.5rem", backgroundColor: "#fafafa", overflowX: "auto" }}>
              <div style={{ display: "flex", alignItems: "flex-end", gap: "0.5rem", minWidth: "100%", height: chartHeight, paddingBottom: "1rem" }}>
                {dailyStats.map((stat, idx) => {
                  const barHeight = maxDailyCount > 0 ? (stat.count / maxDailyCount) * (chartHeight - 40) : 0
                  return (
                    <div key={idx} style={{ flex: 1, minWidth: "40px", display: "flex", flexDirection: "column", alignItems: "center", gap: "0.5rem" }} title={`${stat._id}: ${stat.count} sent`}>
                      <div style={{ width: "100%", height: `${barHeight}px`, backgroundColor: "#3b82f6", borderRadius: "4px 4px 0 0", transition: "all 0.2s", cursor: "pointer", minHeight: barHeight > 0 ? "4px" : "0" }}
                        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#1e40af"; e.currentTarget.style.opacity = "0.8" }}
                        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "#3b82f6"; e.currentTarget.style.opacity = "1" }} />
                      <span style={{ fontSize: "0.65rem", color: "#6b7280", textAlign: "center", width: "100%", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{stat._id}</span>
                    </div>
                  )
                })}
              </div>
              <div style={{ marginTop: "1rem", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem" }}>
                <div style={{ padding: "0.75rem", backgroundColor: "#d1fae5", borderRadius: "8px" }}>
                  <p style={{ fontSize: "0.8rem", color: "#065f46", fontWeight: "600", marginBottom: "0.25rem" }}>Days with data: {dailyStats.length}</p>
                  <p style={{ fontSize: "0.8rem", color: "#047857" }}>Avg/day: {dailyStats.length > 0 ? (dailyStats.reduce((sum, d) => sum + d.count, 0) / dailyStats.length).toFixed(0) : 0}</p>
                </div>
                <div style={{ padding: "0.75rem", backgroundColor: "#dbeafe", borderRadius: "8px" }}>
                  <p style={{ fontSize: "0.8rem", color: "#1e40af", fontWeight: "600", marginBottom: "0.25rem" }}>Peak day</p>
                  <p style={{ fontSize: "0.8rem", color: "#1e40af" }}>{dailyStats.length > 0 ? `${Math.max(...dailyStats.map(d => d.count || 0)).toLocaleString()} emails` : "N/A"}</p>
                </div>
              </div>
            </div>
          )}
        </div>

        <div>
          <h3 style={{ fontSize: "1.125rem", fontWeight: "700", color: "#111827", marginBottom: "1rem" }}>Panelists Registered by Country</h3>
          {registrationLoading ? (
            <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem 0" }}>Loading registration statistics...</p>
          ) : sortedCountries.length === 0 ? (
            <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem 0" }}>No registrations yet</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                    {["Country", "Registered", "% of Total"].map((h, i) => (
                      <th key={h} style={{ padding: "0.75rem 1rem", textAlign: i === 0 ? "left" : "right", fontWeight: "700", color: "#111827", fontSize: "0.875rem" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedCountries.map(([country, count]) => {
                    const totalReg = Object.values(registrationStats).reduce((a, b) => a + b, 0)
                    const percentage = totalReg > 0 ? ((count / totalReg) * 100).toFixed(1) : 0
                    return (
                      <tr key={country} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{ padding: "0.75rem 1rem", color: "#1f2937", fontSize: "0.875rem", fontWeight: "600" }}>{country}</td>
                        <td style={{ padding: "0.75rem 1rem", textAlign: "right", color: "#1f2937", fontSize: "0.875rem", fontWeight: "600" }}>{count.toLocaleString()}</td>
                        <td style={{ padding: "0.75rem 1rem", textAlign: "right", color: "#6b7280", fontSize: "0.875rem" }}>{percentage}%</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* ── SFW Panel section ──────────────────────────────────────────────── */}
      <div className="card" style={{ marginTop: "1.5rem" }}>
        <div className="card-header">
          <div>
            <h2 className="card-title">SFW Panel — panel.surveyfieldwork.com</h2>
            <p className="card-description">Live signup and survey activity from the SurveyFieldwork panelist database</p>
          </div>
          <button onClick={fetchSfwPanelData} disabled={sfwLoading}
            style={{ padding: "0.5rem 1rem", background: sfwLoading ? "#e5e7eb" : "#f97316", color: sfwLoading ? "#9ca3af" : "#fff", border: "none", borderRadius: "8px", cursor: sfwLoading ? "default" : "pointer", fontSize: "0.875rem", fontWeight: "600" }}>
            {sfwLoading ? "Loading…" : "↻ Refresh"}
          </button>
        </div>

        {sfwLoading && !sfwOverview ? (
          <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem 0" }}>Loading SFW panel data…</p>
        ) : sfwOverview ? (
          <>
            {/* User overview cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
              <StatCard label="Total Panelists" value={sfwOverview.users.total} sub="All-time signups" color="#7c3aed" />
              <StatCard label="Joined Today" value={sfwOverview.users.today} sub="New today" color="#059669" />
              <StatCard label="This Week" value={sfwOverview.users.this_week} sub="Last 7 days" color="#0284c7" />
              <StatCard label="Active (7d)" value={sfwOverview.users.active_week} sub="Active last 7 days" color="#d97706" />
            </div>

            {/* Survey stats */}
            <h3 style={{ fontSize: "1rem", fontWeight: "700", color: "#111827", marginBottom: "1rem" }}>Survey Activity</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
              <StatCard label="Total Attempts" value={sfwOverview.surveys.total} sub="All survey entries" color="#4b5563" />
              <StatCard label="Completed" value={sfwOverview.surveys.complete} sub={`${sfwOverview.surveys.completion_rate}% rate`} color="#059669" />
              <StatCard label="Terminated" value={sfwOverview.surveys.terminate} sub="Screen out" color="#dc2626" />
              <StatCard label="Quota Full" value={sfwOverview.surveys.quotafull} sub="" color="#d97706" />
            </div>

            {/* Level + Source */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.5rem", marginBottom: "2rem" }}>
              <div style={{ border: "1px solid #e5e7eb", borderRadius: "10px", padding: "1.25rem" }}>
                <p style={{ fontWeight: "700", color: "#111827", marginBottom: "1rem" }}>Level Distribution</p>
                {["bronze", "silver", "gold"].map(lvl => {
                  const count = sfwOverview.levels?.[lvl] || 0
                  const total = Object.values(sfwOverview.levels || {}).reduce((s, n) => s + n, 0)
                  const pct = total ? Math.round((count / total) * 100) : 0
                  const colors = { bronze: "#f59e0b", silver: "#9ca3af", gold: "#eab308" }
                  return (
                    <div key={lvl} style={{ marginBottom: "0.75rem" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "#6b7280", marginBottom: "0.25rem" }}>
                        <span style={{ textTransform: "capitalize", fontWeight: "600" }}>{lvl}</span>
                        <span>{count} ({pct}%)</span>
                      </div>
                      <div style={{ height: "6px", background: "#f3f4f6", borderRadius: "99px" }}>
                        <div style={{ height: "6px", width: `${pct}%`, background: colors[lvl], borderRadius: "99px" }} />
                      </div>
                    </div>
                  )
                })}
              </div>

              <div style={{ border: "1px solid #e5e7eb", borderRadius: "10px", padding: "1.25rem" }}>
                <p style={{ fontWeight: "700", color: "#111827", marginBottom: "1rem" }}>Signup Source</p>
                {Object.entries(sfwOverview.sources || {}).map(([src, count]) => {
                  const total = Object.values(sfwOverview.sources || {}).reduce((s, n) => s + n, 0)
                  const pct = total ? Math.round((count / total) * 100) : 0
                  const colors = { organic: "#10b981", referral: "#6366f1", campaign: "#a855f7" }
                  return (
                    <div key={src} style={{ marginBottom: "0.75rem" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.8rem", color: "#6b7280", marginBottom: "0.25rem" }}>
                        <span style={{ textTransform: "capitalize", fontWeight: "600" }}>{src || "unknown"}</span>
                        <span>{count} ({pct}%)</span>
                      </div>
                      <div style={{ height: "6px", background: "#f3f4f6", borderRadius: "99px" }}>
                        <div style={{ height: "6px", width: `${pct}%`, background: colors[src] || "#6b7280", borderRadius: "99px" }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Country breakdown */}
            <h3 style={{ fontSize: "1rem", fontWeight: "700", color: "#111827", marginBottom: "1rem" }}>Signups by Country</h3>
            {sfwCountries.length === 0 ? (
              <p style={{ color: "#6b7280", textAlign: "center", padding: "1rem 0" }}>No data</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.875rem" }}>
                  <thead>
                    <tr style={{ borderBottom: "2px solid #e5e7eb", background: "#f9fafb" }}>
                      {["Country", "Total", "Share", "Today", "This Week"].map((h, i) => (
                        <th key={h} style={{ padding: "0.75rem 1rem", textAlign: i === 0 ? "left" : "right", fontWeight: "700", color: "#374151" }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sfwCountries.map(({ country, total, today, this_week }) => {
                      const pct = sfwTotal ? Math.round((total / sfwTotal) * 100) : 0
                      return (
                        <tr key={country} style={{ borderBottom: "1px solid #f3f4f6" }}>
                          <td style={{ padding: "0.75rem 1rem", fontWeight: "600", color: "#1f2937" }}>
                            <span style={{ color: "#9ca3af", fontFamily: "monospace", marginRight: "0.5rem", fontSize: "0.75rem" }}>{country}</span>
                            {countryName(country)}
                          </td>
                          <td style={{ padding: "0.75rem 1rem", textAlign: "right", fontWeight: "700", color: "#111827" }}>{total}</td>
                          <td style={{ padding: "0.75rem 1rem", textAlign: "right" }}>
                            <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: "0.5rem" }}>
                              <div style={{ width: "60px", height: "6px", background: "#f3f4f6", borderRadius: "99px" }}>
                                <div style={{ width: `${pct}%`, height: "6px", background: "#f97316", borderRadius: "99px" }} />
                              </div>
                              <span style={{ color: "#6b7280", width: "36px", textAlign: "right" }}>{pct}%</span>
                            </div>
                          </td>
                          <td style={{ padding: "0.75rem 1rem", textAlign: "right", color: "#059669", fontWeight: today > 0 ? "700" : "400" }}>{today || 0}</td>
                          <td style={{ padding: "0.75rem 1rem", textAlign: "right", color: "#0284c7" }}>{this_week || 0}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : (
          <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem 0" }}>Failed to load SFW panel data.</p>
        )}
      </div>
    </div>
  )
}

export default PanelDashboard
