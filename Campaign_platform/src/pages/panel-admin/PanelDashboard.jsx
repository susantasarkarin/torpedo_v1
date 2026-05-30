import { useState, useEffect } from "react"
import { buildApiUrl } from "../../config"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

function PanelDashboard() {
  const [dailyStats, setDailyStats] = useState([])
  const [dailyLoading, setDailyLoading] = useState(false)
  const [registrationStats, setRegistrationStats] = useState({})
  const [registrationLoading, setRegistrationLoading] = useState(false)
  const [totalSent, setTotalSent] = useState(0)
  const [totalBounced, setTotalBounced] = useState(0)
  const [totalConfirmed, setTotalConfirmed] = useState(0)
  const [days, setDays] = useState(30)

  useEffect(() => {
    fetchDailyStats()
    fetchRegistrationStats()
  }, [days])

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

  // Calculate max value for chart scaling
  const maxDailyCount = dailyStats.length > 0 ? Math.max(...dailyStats.map(d => d.count || 0)) : 0
  const chartHeight = 300

  // Sort countries by count (descending) for the registration table
  const sortedCountries = Object.entries(registrationStats)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15) // Top 15 countries

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <div>
            <h2 className="card-title">Panel Dashboard</h2>
            <p className="card-description">Monitor email sending activity and panelist registrations</p>
          </div>
        </div>

        {/* Overview Stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "1rem", marginBottom: "2rem" }}>
          <div style={{
            padding: "1.5rem",
            border: "1px solid #e5e7eb",
            borderRadius: "12px",
            backgroundColor: "#f9fafb",
          }}>
            <p style={{ fontSize: "0.875rem", color: "#6b7280", fontWeight: "600", marginBottom: "0.5rem" }}>
              Total Sent
            </p>
            <p style={{ fontSize: "2rem", fontWeight: "700", color: "#059669", marginBottom: "0.25rem" }}>
              {totalSent.toLocaleString()}
            </p>
            <p style={{ fontSize: "0.8rem", color: "#9ca3af" }}>All-time invitations sent</p>
          </div>

          <div style={{
            padding: "1.5rem",
            border: "1px solid #e5e7eb",
            borderRadius: "12px",
            backgroundColor: "#f9fafb",
          }}>
            <p style={{ fontSize: "0.875rem", color: "#6b7280", fontWeight: "600", marginBottom: "0.5rem" }}>
              Confirmed
            </p>
            <p style={{ fontSize: "2rem", fontWeight: "700", color: "#0284c7", marginBottom: "0.25rem" }}>
              {totalConfirmed.toLocaleString()}
            </p>
            <p style={{ fontSize: "0.8rem", color: "#9ca3af" }}>Double opt-in completed</p>
          </div>

          <div style={{
            padding: "1.5rem",
            border: "1px solid #e5e7eb",
            borderRadius: "12px",
            backgroundColor: "#f9fafb",
          }}>
            <p style={{ fontSize: "0.875rem", color: "#6b7280", fontWeight: "600", marginBottom: "0.5rem" }}>
              Bounced
            </p>
            <p style={{ fontSize: "2rem", fontWeight: "700", color: "#dc2626", marginBottom: "0.25rem" }}>
              {totalBounced.toLocaleString()}
            </p>
            <p style={{ fontSize: "0.8rem", color: "#9ca3af" }}>Failed delivery</p>
          </div>

          <div style={{
            padding: "1.5rem",
            border: "1px solid #e5e7eb",
            borderRadius: "12px",
            backgroundColor: "#f9fafb",
          }}>
            <p style={{ fontSize: "0.875rem", color: "#6b7280", fontWeight: "600", marginBottom: "0.5rem" }}>
              Conversion Rate
            </p>
            <p style={{ fontSize: "2rem", fontWeight: "700", color: "#7c3aed", marginBottom: "0.25rem" }}>
              {totalSent > 0 ? ((totalConfirmed / totalSent) * 100).toFixed(1) : 0}%
            </p>
            <p style={{ fontSize: "0.8rem", color: "#9ca3af" }}>Confirmed / Total sent</p>
          </div>
        </div>

        {/* Daily Stats Chart */}
        <div style={{ marginBottom: "2rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h3 style={{ fontSize: "1.125rem", fontWeight: "700", color: "#111827" }}>
              Daily Email Activity
            </h3>
            <select
              value={days}
              onChange={(e) => setDays(parseInt(e.target.value))}
              style={{
                padding: "0.5rem 0.75rem",
                border: "1px solid #d1d5db",
                borderRadius: "6px",
                fontSize: "0.875rem",
                backgroundColor: "#fff",
              }}
            >
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
            <div style={{
              border: "1px solid #e5e7eb",
              borderRadius: "12px",
              padding: "1.5rem",
              backgroundColor: "#fafafa",
              overflowX: "auto",
            }}>
              <div style={{ display: "flex", alignItems: "flex-end", gap: "0.5rem", minWidth: "100%", height: chartHeight, paddingBottom: "1rem" }}>
                {dailyStats.map((stat, idx) => {
                  const barHeight = maxDailyCount > 0 ? (stat.count / maxDailyCount) * (chartHeight - 40) : 0
                  return (
                    <div
                      key={idx}
                      style={{
                        flex: 1,
                        minWidth: "40px",
                        display: "flex",
                        flexDirection: "column",
                        alignItems: "center",
                        gap: "0.5rem",
                      }}
                      title={`${stat._id}: ${stat.count} sent`}
                    >
                      <div
                        style={{
                          width: "100%",
                          height: `${barHeight}px`,
                          backgroundColor: "#3b82f6",
                          borderRadius: "4px 4px 0 0",
                          transition: "all 0.2s",
                          cursor: "pointer",
                          minHeight: barHeight > 0 ? "4px" : "0",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.backgroundColor = "#1e40af"
                          e.currentTarget.style.opacity = "0.8"
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.backgroundColor = "#3b82f6"
                          e.currentTarget.style.opacity = "1"
                        }}
                      />
                      <span style={{
                        fontSize: "0.65rem",
                        color: "#6b7280",
                        textAlign: "center",
                        width: "100%",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}>
                        {stat._id}
                      </span>
                    </div>
                  )
                })}
              </div>

              <div style={{ marginTop: "1rem", display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "1rem" }}>
                <div style={{ padding: "0.75rem", backgroundColor: "#d1fae5", borderRadius: "8px" }}>
                  <p style={{ fontSize: "0.8rem", color: "#065f46", fontWeight: "600", marginBottom: "0.25rem" }}>
                    Days with data: {dailyStats.length}
                  </p>
                  <p style={{ fontSize: "0.8rem", color: "#047857" }}>
                    Avg/day: {dailyStats.length > 0 ? (dailyStats.reduce((sum, d) => sum + d.count, 0) / dailyStats.length).toFixed(0) : 0}
                  </p>
                </div>
                <div style={{ padding: "0.75rem", backgroundColor: "#dbeafe", borderRadius: "8px" }}>
                  <p style={{ fontSize: "0.8rem", color: "#1e40af", fontWeight: "600", marginBottom: "0.25rem" }}>
                    Peak day
                  </p>
                  <p style={{ fontSize: "0.8rem", color: "#1e40af" }}>
                    {dailyStats.length > 0 ? `${Math.max(...dailyStats.map(d => d.count || 0)).toLocaleString()} emails` : "N/A"}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Registrations by Country */}
        <div>
          <h3 style={{ fontSize: "1.125rem", fontWeight: "700", color: "#111827", marginBottom: "1rem" }}>
            Panelists Registered by Country
          </h3>

          {registrationLoading ? (
            <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem 0" }}>Loading registration statistics...</p>
          ) : sortedCountries.length === 0 ? (
            <p style={{ color: "#6b7280", textAlign: "center", padding: "2rem 0" }}>No registrations yet</p>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                    <th style={{
                      padding: "0.75rem 1rem",
                      textAlign: "left",
                      fontWeight: "700",
                      color: "#111827",
                      fontSize: "0.875rem",
                    }}>
                      Country
                    </th>
                    <th style={{
                      padding: "0.75rem 1rem",
                      textAlign: "right",
                      fontWeight: "700",
                      color: "#111827",
                      fontSize: "0.875rem",
                    }}>
                      Registered
                    </th>
                    <th style={{
                      padding: "0.75rem 1rem",
                      textAlign: "right",
                      fontWeight: "700",
                      color: "#111827",
                      fontSize: "0.875rem",
                    }}>
                      % of Total
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {sortedCountries.map(([country, count]) => {
                    const totalReg = Object.values(registrationStats).reduce((a, b) => a + b, 0)
                    const percentage = totalReg > 0 ? ((count / totalReg) * 100).toFixed(1) : 0
                    return (
                      <tr key={country} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={{
                          padding: "0.75rem 1rem",
                          color: "#1f2937",
                          fontSize: "0.875rem",
                          fontWeight: "600",
                        }}>
                          {country}
                        </td>
                        <td style={{
                          padding: "0.75rem 1rem",
                          textAlign: "right",
                          color: "#1f2937",
                          fontSize: "0.875rem",
                          fontWeight: "600",
                        }}>
                          {count.toLocaleString()}
                        </td>
                        <td style={{
                          padding: "0.75rem 1rem",
                          textAlign: "right",
                          color: "#6b7280",
                          fontSize: "0.875rem",
                        }}>
                          {percentage}%
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default PanelDashboard
