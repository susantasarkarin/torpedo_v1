function Leads() {
  const sampleLeads = [
    { id: 1, name: "John Smith", email: "john@company.com", status: "New", score: 85 },
    { id: 2, name: "Sarah Johnson", email: "sarah@business.com", status: "Qualified", score: 92 },
    { id: 3, name: "Mike Davis", email: "mike@startup.com", status: "Contacted", score: 78 },
    { id: 4, name: "Lisa Wilson", email: "lisa@enterprise.com", status: "Nurturing", score: 88 },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Lead Management</h2>
          <p className="card-description">Track and manage your sales leads through the pipeline.</p>
        </div>
        <div className="mb-4">
          <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
            Add New Lead
          </button>
          <button className="btn btn-secondary">Import Leads</button>
        </div>
        <div className="card">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                <th style={{ padding: "1rem", textAlign: "left" }}>Name</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Email</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Status</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Score</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sampleLeads.map((lead) => (
                <tr key={lead.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "1rem" }}>{lead.name}</td>
                  <td style={{ padding: "1rem" }}>{lead.email}</td>
                  <td style={{ padding: "1rem" }}>
                    <span
                      style={{
                        padding: "0.25rem 0.75rem",
                        borderRadius: "9999px",
                        fontSize: "0.75rem",
                        backgroundColor: "#dbeafe",
                        color: "#1e40af",
                      }}
                    >
                      {lead.status}
                    </span>
                  </td>
                  <td style={{ padding: "1rem" }}>{lead.score}</td>
                  <td style={{ padding: "1rem" }}>
                    <button className="btn btn-outline" style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem" }}>
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

export default Leads
