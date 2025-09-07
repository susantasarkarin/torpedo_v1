function Reports() {
  const campaignMetrics = [
    { metric: "Total Campaigns", value: "24", change: "+12%", trend: "up" },
    { metric: "Emails Sent", value: "15,847", change: "+8.3%", trend: "up" },
    { metric: "Open Rate", value: "34.2%", change: "+2.1%", trend: "up" },
    { metric: "Click Rate", value: "4.8%", change: "-0.3%", trend: "down" },
    { metric: "Conversion Rate", value: "2.1%", change: "+0.5%", trend: "up" },
    { metric: "Unsubscribe Rate", value: "0.8%", change: "-0.2%", trend: "up" },
  ]

  const topCampaigns = [
    { name: "Holiday Promotion", opens: 2156, clicks: 342, conversions: 89, revenue: "$12,450" },
    { name: "Product Launch", opens: 1834, clicks: 298, conversions: 67, revenue: "$9,870" },
    { name: "Customer Retention", opens: 1456, clicks: 234, conversions: 45, revenue: "$6,780" },
    { name: "Newsletter Q1", opens: 1289, clicks: 189, conversions: 34, revenue: "$4,560" },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Campaign Reports</h2>
          <p className="card-description">
            Analyze your email campaign performance with detailed analytics and insights.
          </p>
        </div>

        <div className="mb-6">
          <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
            View Reports
          </button>
          <button className="btn btn-secondary" style={{ marginRight: "1rem" }}>
            Export Data
          </button>
          <button className="btn btn-outline">Schedule Report</button>
        </div>

        <div className="grid grid-cols-3 mb-6">
          {campaignMetrics.map((item, index) => (
            <div key={index} className="card">
              <h3 className="card-title">{item.metric}</h3>
              <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#1e293b", marginBottom: "0.5rem" }}>
                {item.value}
              </p>
              <p
                style={{
                  fontSize: "0.875rem",
                  color: item.trend === "up" ? "#10b981" : "#ef4444",
                  display: "flex",
                  alignItems: "center",
                }}
              >
                <span style={{ marginRight: "0.25rem" }}>{item.trend === "up" ? "↗" : "↘"}</span>
                {item.change} from last month
              </p>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2 mb-6">
          <div className="card">
            <h3 className="card-title mb-4">Campaign Performance Chart</h3>
            <div
              style={{
                height: "200px",
                backgroundColor: "#f8fafc",
                borderRadius: "6px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "1px solid #e2e8f0",
              }}
            >
              <p style={{ color: "#64748b" }}>Interactive Chart Placeholder</p>
            </div>
          </div>
          <div className="card">
            <h3 className="card-title mb-4">Engagement Trends</h3>
            <div
              style={{
                height: "200px",
                backgroundColor: "#f8fafc",
                borderRadius: "6px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                border: "1px solid #e2e8f0",
              }}
            >
              <p style={{ color: "#64748b" }}>Trend Analysis Placeholder</p>
            </div>
          </div>
        </div>

        <div className="card">
          <h3 className="card-title mb-4">Top Performing Campaigns</h3>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                <th style={{ padding: "1rem", textAlign: "left" }}>Campaign Name</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Opens</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Clicks</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Conversions</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Revenue</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {topCampaigns.map((campaign, index) => (
                <tr key={index} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "1rem", fontWeight: "600" }}>{campaign.name}</td>
                  <td style={{ padding: "1rem" }}>{campaign.opens.toLocaleString()}</td>
                  <td style={{ padding: "1rem" }}>{campaign.clicks.toLocaleString()}</td>
                  <td style={{ padding: "1rem" }}>{campaign.conversions}</td>
                  <td style={{ padding: "1rem", fontWeight: "600", color: "#10b981" }}>{campaign.revenue}</td>
                  <td style={{ padding: "1rem" }}>
                    <button className="btn btn-outline" style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem" }}>
                      View Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3 className="card-title mb-4">Advanced Analytics</h3>
          <div className="grid grid-cols-2">
            <div>
              <h4 style={{ fontWeight: "600", marginBottom: "1rem" }}>A/B Test Results</h4>
              <div
                style={{
                  padding: "1rem",
                  backgroundColor: "#f8fafc",
                  borderRadius: "6px",
                  border: "1px solid #e2e8f0",
                  marginBottom: "1rem",
                }}
              >
                <p style={{ fontSize: "0.875rem", color: "#64748b" }}>
                  Subject Line A: "Don't Miss Out!" - 32.1% open rate
                </p>
                <p style={{ fontSize: "0.875rem", color: "#64748b" }}>
                  Subject Line B: "Limited Time Offer" - 36.4% open rate
                </p>
                <p style={{ fontSize: "0.875rem", fontWeight: "600", color: "#10b981", marginTop: "0.5rem" }}>
                  Winner: Subject Line B (+4.3% improvement)
                </p>
              </div>
            </div>
            <div>
              <h4 style={{ fontWeight: "600", marginBottom: "1rem" }}>Segmentation Performance</h4>
              <div
                style={{
                  padding: "1rem",
                  backgroundColor: "#f8fafc",
                  borderRadius: "6px",
                  border: "1px solid #e2e8f0",
                }}
              >
                <p style={{ fontSize: "0.875rem", color: "#64748b", marginBottom: "0.5rem" }}>
                  VIP Customers: 45.2% open rate
                </p>
                <p style={{ fontSize: "0.875rem", color: "#64748b", marginBottom: "0.5rem" }}>
                  New Subscribers: 28.7% open rate
                </p>
                <p style={{ fontSize: "0.875rem", color: "#64748b" }}>Inactive Users: 12.3% open rate</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Reports
