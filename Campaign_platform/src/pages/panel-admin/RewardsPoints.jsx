import { useState, useEffect } from "react"
import { buildApiUrl } from "../../config"

const PANEL_ADMIN_API_PREFIX = "/api/panel-admin"

function RewardsPoints() {
  const [stats, setStats] = useState({ totalIssued: 0, totalRedeemed: 0, pendingRedemptions: 0 })
  const [transactions, setTransactions] = useState([])
  const [redemptions, setRedemptions] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState("transactions")

  useEffect(() => {
    fetchRewardsData()
  }, [])

  const fetchRewardsData = async () => {
    const sessionId = localStorage.getItem("session_id")
    try {
      const [statsRes, txRes, redemptionRes] = await Promise.all([
        fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/stats/`), { headers: { Authorization: sessionId } }),
        fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/rewards/`), { headers: { Authorization: sessionId } }),
        fetch(buildApiUrl(`${PANEL_ADMIN_API_PREFIX}/rewards/redemptions`), { headers: { Authorization: sessionId } }),
      ])

      if (statsRes.ok) {
        const data = await statsRes.json()
        setStats({
          totalIssued: data.totalRewardsIssued || 0,
          totalRedeemed: data.totalRedeemed || 0,
          pendingRedemptions: data.pendingRedemptions || 0,
        })
      }
      if (txRes.ok) {
        const data = await txRes.json()
        setTransactions(data.results || data || [])
      }
      if (redemptionRes.ok) {
        const data = await redemptionRes.json()
        setRedemptions(data.results || data || [])
      }
    } catch (err) {
      console.error("Failed to fetch rewards data:", err)
    } finally {
      setLoading(false)
    }
  }

  const tabStyle = (tab) => ({
    padding: "0.75rem 1.5rem",
    border: "none",
    borderBottom: activeTab === tab ? "3px solid #3b82f6" : "3px solid transparent",
    background: "none",
    cursor: "pointer",
    fontWeight: activeTab === tab ? "600" : "400",
    color: activeTab === tab ? "#3b82f6" : "#6b7280",
    fontSize: "0.95rem",
  })

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Rewards & Points</h2>
          <p className="card-description">Manage reward points, transactions, and redemption requests.</p>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-3 mb-6">
          <div className="card">
            <h3 className="card-title">Total Points Issued</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#10b981" }}>
              {loading ? "..." : stats.totalIssued}
            </p>
          </div>
          <div className="card">
            <h3 className="card-title">Total Redeemed</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6" }}>
              {loading ? "..." : stats.totalRedeemed}
            </p>
          </div>
          <div className="card">
            <h3 className="card-title">Pending Redemptions</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#f59e0b" }}>
              {loading ? "..." : stats.pendingRedemptions}
            </p>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ borderBottom: "1px solid #e5e7eb", marginBottom: "1.5rem" }}>
          <button style={tabStyle("transactions")} onClick={() => setActiveTab("transactions")}>
            Transaction History
          </button>
          <button style={tabStyle("redemptions")} onClick={() => setActiveTab("redemptions")}>
            Redemption Requests
          </button>
        </div>

        {/* Transactions Tab */}
        {activeTab === "transactions" && (
          <div>
            {loading ? (
              <p style={{ color: "#6b7280" }}>Loading transactions...</p>
            ) : transactions.length === 0 ? (
              <p style={{ color: "#6b7280" }}>No transactions found.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                      <th style={thStyle}>Panelist</th>
                      <th style={thStyle}>Type</th>
                      <th style={thStyle}>Amount</th>
                      <th style={thStyle}>Description</th>
                      <th style={thStyle}>Status</th>
                      <th style={thStyle}>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {transactions.map((tx, i) => (
                      <tr key={tx._id || tx.id || i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={tdStyle}>{tx.panelist_name || tx.panelist_email || tx.panelist_id || "-"}</td>
                        <td style={tdStyle}>
                          <span style={{
                            fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "9999px",
                            backgroundColor: tx.type === "earned" ? "#d1fae5" : "#dbeafe",
                            color: tx.type === "earned" ? "#065f46" : "#1e40af",
                          }}>
                            {tx.type || "-"}
                          </span>
                        </td>
                        <td style={tdStyle}>{tx.amount ?? 0}</td>
                        <td style={tdStyle}>{tx.description || "-"}</td>
                        <td style={tdStyle}>{tx.status || "completed"}</td>
                        <td style={tdStyle}>
                          {tx.created_at ? new Date(tx.created_at).toLocaleDateString() : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Redemptions Tab */}
        {activeTab === "redemptions" && (
          <div>
            {loading ? (
              <p style={{ color: "#6b7280" }}>Loading redemption requests...</p>
            ) : redemptions.length === 0 ? (
              <p style={{ color: "#6b7280" }}>No redemption requests found.</p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr style={{ borderBottom: "2px solid #e5e7eb" }}>
                      <th style={thStyle}>Panelist</th>
                      <th style={thStyle}>Amount</th>
                      <th style={thStyle}>Method</th>
                      <th style={thStyle}>Status</th>
                      <th style={thStyle}>Requested</th>
                    </tr>
                  </thead>
                  <tbody>
                    {redemptions.map((r, i) => (
                      <tr key={r._id || r.id || i} style={{ borderBottom: "1px solid #f3f4f6" }}>
                        <td style={tdStyle}>{r.panelist_name || r.panelist_email || "-"}</td>
                        <td style={tdStyle}>{r.amount ?? 0}</td>
                        <td style={tdStyle}>{r.method || "UPI"}</td>
                        <td style={tdStyle}>
                          <span style={{
                            fontSize: "0.75rem", padding: "0.2rem 0.6rem", borderRadius: "9999px",
                            backgroundColor: r.status === "completed" ? "#d1fae5" :
                              r.status === "pending" ? "#fef3c7" : "#fee2e2",
                            color: r.status === "completed" ? "#065f46" :
                              r.status === "pending" ? "#92400e" : "#991b1b",
                          }}>
                            {r.status || "pending"}
                          </span>
                        </td>
                        <td style={tdStyle}>
                          {r.created_at ? new Date(r.created_at).toLocaleDateString() : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

const thStyle = { textAlign: "left", padding: "0.75rem", fontSize: "0.875rem", color: "#6b7280" }
const tdStyle = { padding: "0.75rem", fontSize: "0.875rem" }

export default RewardsPoints
