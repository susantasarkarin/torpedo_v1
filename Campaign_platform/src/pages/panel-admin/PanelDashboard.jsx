import { useState, useEffect } from "react"
import { buildApiUrl } from "../../config"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

function PanelDashboard() {
  const [stats, setStats] = useState({
    totalPanelists: 0,
    activePanelists: 0,
    pendingApprovals: 0,
    totalRewardsIssued: 0,
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStats()
  }, [])

  const fetchStats = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const res = await fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/stats/`), {
        headers: { Authorization: sessionId },
      })
      if (res.ok) {
        const data = await res.json()
        setStats(data)
      }
    } catch (err) {
      console.error("Failed to fetch panel stats:", err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Panel Dashboard</h2>
          <p className="card-description">
            Overview of survey panel activity, panelist registrations, and reward metrics.
          </p>
        </div>

        <div className="grid grid-cols-2 mb-6">
          <div className="card">
            <h3 className="card-title">Total Panelists</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6", marginBottom: "0.5rem" }}>
              {loading ? "..." : stats.totalPanelists}
            </p>
            <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>Registered users</p>
          </div>
          <div className="card">
            <h3 className="card-title">Active Panelists</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#10b981", marginBottom: "0.5rem" }}>
              {loading ? "..." : stats.activePanelists}
            </p>
            <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>Currently active</p>
          </div>
          <div className="card">
            <h3 className="card-title">Pending Approvals</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#f59e0b", marginBottom: "0.5rem" }}>
              {loading ? "..." : stats.pendingApprovals}
            </p>
            <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>Awaiting review</p>
          </div>
          <div className="card">
            <h3 className="card-title">Rewards Issued</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#8b5cf6", marginBottom: "0.5rem" }}>
              {loading ? "..." : stats.totalRewardsIssued}
            </p>
            <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>Total rewards given</p>
          </div>
        </div>

        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">Quick Actions</h3>
            <div className="grid" style={{ gap: "1rem", marginTop: "1rem" }}>
              <button className="btn btn-primary" onClick={() => window.location.href = "/admin/panel-admin/panelists"}>
                View Panelists
              </button>
              <button className="btn btn-secondary" onClick={() => window.location.href = "/admin/panel-admin/rewards"}>
                Manage Rewards
              </button>
              <button className="btn btn-outline" onClick={() => window.location.href = "/admin/panel-admin/settings"}>
                Panel Settings
              </button>
            </div>
          </div>

          <div className="card">
            <h3 className="card-title">Recent Activity</h3>
            <p style={{ color: "#6b7280", marginTop: "1rem" }}>
              Panel activity feed coming soon.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default PanelDashboard
