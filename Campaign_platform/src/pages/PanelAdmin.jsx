import { useState, useEffect } from "react"
import { API_BASE_URL, buildApiUrl } from "../config"

function PanelAdmin() {
  const [stats, setStats] = useState({
    totalPanelists: 0,
    activePanelists: 0,
    pendingApprovals: 0,
    totalRewardsIssued: 0,
  })
  const [panelists, setPanelists] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchPanelData()
  }, [])

  const fetchPanelData = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const [statsRes, panelistsRes] = await Promise.all([
        fetch(buildApiUrl("/panel-admin/stats/"), {
          headers: { Authorization: sessionId },
        }),
        fetch(buildApiUrl("/panel-admin/panelists/"), {
          headers: { Authorization: sessionId },
        }),
      ])

      if (statsRes.ok) {
        const statsData = await statsRes.json()
        setStats(statsData)
      }
      if (panelistsRes.ok) {
        const panelistsData = await panelistsRes.json()
        setPanelists(panelistsData.results || panelistsData || [])
      }
    } catch (err) {
      console.error("Failed to fetch panel data:", err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Panel Administration</h2>
          <p className="card-description">
            Manage survey panelists, rewards, approvals, and panel settings.
          </p>
        </div>

        {/* Stats Overview */}
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

        {/* Admin Actions */}
        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">Panelist Management</h3>
            <div className="grid" style={{ gap: "1rem", marginTop: "1rem" }}>
              <button className="btn btn-primary">View All Panelists</button>
              <button className="btn btn-secondary">Pending Approvals</button>
              <button className="btn btn-outline">Blocked Users</button>
              <button className="btn btn-outline">Export Data</button>
            </div>
          </div>

          <div className="card">
            <h3 className="card-title">Rewards & Points</h3>
            <div className="grid" style={{ gap: "1rem", marginTop: "1rem" }}>
              <button className="btn btn-primary">Manage Rewards</button>
              <button className="btn btn-secondary">Redemption Requests</button>
              <button className="btn btn-outline">Points Configuration</button>
              <button className="btn btn-outline">Reward History</button>
            </div>
          </div>
        </div>

        {/* Recent Panelists Table */}
        <div className="card">
          <h3 className="card-title">Recent Panelists</h3>
          <div style={{ marginTop: "1rem", overflowX: "auto" }}>
            {loading ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>Loading...</p>
            ) : panelists.length === 0 ? (
              <p style={{ color: "#6b7280", padding: "1rem 0" }}>No panelists found.</p>
            ) : (
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                    <th style={{ textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#6b7280" }}>Name</th>
                    <th style={{ textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#6b7280" }}>Email</th>
                    <th style={{ textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#6b7280" }}>Status</th>
                    <th style={{ textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#6b7280" }}>Points</th>
                    <th style={{ textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#6b7280" }}>Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {panelists.slice(0, 10).map((panelist, index) => (
                    <tr key={panelist.id || index} style={{ borderBottom: "1px solid #f3f4f6" }}>
                      <td style={{ padding: "0.75rem", fontWeight: "500" }}>
                        {panelist.first_name} {panelist.last_name}
                      </td>
                      <td style={{ padding: "0.75rem", color: "#6b7280" }}>{panelist.email}</td>
                      <td style={{ padding: "0.75rem" }}>
                        <span
                          style={{
                            fontSize: "0.75rem",
                            padding: "0.25rem 0.75rem",
                            borderRadius: "9999px",
                            backgroundColor: panelist.is_active ? "#d1fae5" : "#fee2e2",
                            color: panelist.is_active ? "#065f46" : "#991b1b",
                          }}
                        >
                          {panelist.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td style={{ padding: "0.75rem" }}>{panelist.points ?? 0}</td>
                      <td style={{ padding: "0.75rem", color: "#6b7280", fontSize: "0.875rem" }}>
                        {panelist.created_at ? new Date(panelist.created_at).toLocaleDateString() : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* Panel Settings */}
        <div className="card">
          <h3 className="card-title">Panel Settings</h3>
          <div className="grid grid-cols-3" style={{ marginTop: "1rem" }}>
            <button className="btn btn-primary">Signup Configuration</button>
            <button className="btn btn-secondary">Email Templates</button>
            <button className="btn btn-outline">Panel Branding</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default PanelAdmin
