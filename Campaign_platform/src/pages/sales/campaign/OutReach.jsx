function Outreach() {
  const sampleCampaigns = [
    { id: 1, name: "Q1 Product Launch", status: "Active", sent: 1250, opened: 425, clicked: 89, date: "2024-01-15" },
    { id: 2, name: "Customer Retention", status: "Scheduled", sent: 0, opened: 0, clicked: 0, date: "2024-01-20" },
    { id: 3, name: "New Feature Announcement", status: "Draft", sent: 0, opened: 0, clicked: 0, date: "2024-01-18" },
    {
      id: 4,
      name: "Holiday Promotion",
      status: "Completed",
      sent: 2100,
      opened: 756,
      clicked: 142,
      date: "2024-01-10",
    },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Outreach Campaigns</h2>
          <p className="card-description">
            Create and manage your email outreach campaigns to engage with prospects and customers.
          </p>
        </div>

        <div className="mb-6">
          <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
            Create New Campaign
          </button>
          <button className="btn btn-secondary" style={{ marginRight: "1rem" }}>
            Import Campaign
          </button>
          <button className="btn btn-outline">Campaign Templates</button>
        </div>

        <div className="grid grid-cols-3 mb-6">
          <div className="card">
            <h3 className="card-title">Active Campaigns</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#10b981" }}>3</p>
            <p className="card-description">Currently running</p>
          </div>
          <div className="card">
            <h3 className="card-title">Total Sent</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6" }}>3,350</p>
            <p className="card-description">Emails this month</p>
          </div>
          <div className="card">
            <h3 className="card-title">Open Rate</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#f59e0b" }}>35.2%</p>
            <p className="card-description">Average this month</p>
          </div>
        </div>

        <div className="card">
          <h3 className="card-title mb-4">Campaign List</h3>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                <th style={{ padding: "1rem", textAlign: "left" }}>Campaign Name</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Status</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Sent</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Opened</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Clicked</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Date</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sampleCampaigns.map((campaign) => (
                <tr key={campaign.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "1rem", fontWeight: "600" }}>{campaign.name}</td>
                  <td style={{ padding: "1rem" }}>
                    <span
                      style={{
                        padding: "0.25rem 0.75rem",
                        borderRadius: "9999px",
                        fontSize: "0.75rem",
                        backgroundColor:
                          campaign.status === "Active"
                            ? "#dcfce7"
                            : campaign.status === "Completed"
                              ? "#dbeafe"
                              : "#fef3c7",
                        color:
                          campaign.status === "Active"
                            ? "#166534"
                            : campaign.status === "Completed"
                              ? "#1e40af"
                              : "#92400e",
                      }}
                    >
                      {campaign.status}
                    </span>
                  </td>
                  <td style={{ padding: "1rem" }}>{campaign.sent.toLocaleString()}</td>
                  <td style={{ padding: "1rem" }}>{campaign.opened.toLocaleString()}</td>
                  <td style={{ padding: "1rem" }}>{campaign.clicked.toLocaleString()}</td>
                  <td style={{ padding: "1rem" }}>{campaign.date}</td>
                  <td style={{ padding: "1rem" }}>
                    <button
                      className="btn btn-outline"
                      style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem", marginRight: "0.5rem" }}
                    >
                      Edit
                    </button>
                    <button className="btn btn-secondary" style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem" }}>
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default Outreach
