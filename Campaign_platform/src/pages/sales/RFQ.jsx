function RFQ() {
  const sampleRFQs = [
    {
      id: 1,
      title: "Website Development",
      client: "TechCorp Inc.",
      value: "$15,000",
      status: "Pending",
      date: "2024-01-15",
    },
    {
      id: 2,
      title: "Mobile App Design",
      client: "StartupXYZ",
      value: "$8,500",
      status: "Submitted",
      date: "2024-01-12",
    },
    {
      id: 3,
      title: "Marketing Campaign",
      client: "Business Solutions",
      value: "$12,000",
      status: "Won",
      date: "2024-01-10",
    },
    {
      id: 4,
      title: "System Integration",
      client: "Enterprise Ltd.",
      value: "$25,000",
      status: "In Review",
      date: "2024-01-08",
    },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Request for Quotation (RFQ)</h2>
          <p className="card-description">Manage quotation requests and track proposal status.</p>
        </div>
        <div className="mb-4">
          <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
            Create New RFQ
          </button>
          <button className="btn btn-secondary">Import RFQs</button>
        </div>
        <div className="card">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                <th style={{ padding: "1rem", textAlign: "left" }}>RFQ Title</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Client</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Value</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Status</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Date</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sampleRFQs.map((rfq) => (
                <tr key={rfq.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "1rem", fontWeight: "600" }}>{rfq.title}</td>
                  <td style={{ padding: "1rem" }}>{rfq.client}</td>
                  <td style={{ padding: "1rem", fontWeight: "600", color: "#10b981" }}>{rfq.value}</td>
                  <td style={{ padding: "1rem" }}>
                    <span
                      style={{
                        padding: "0.25rem 0.75rem",
                        borderRadius: "9999px",
                        fontSize: "0.75rem",
                        backgroundColor: rfq.status === "Won" ? "#dcfce7" : "#dbeafe",
                        color: rfq.status === "Won" ? "#166534" : "#1e40af",
                      }}
                    >
                      {rfq.status}
                    </span>
                  </td>
                  <td style={{ padding: "1rem" }}>{rfq.date}</td>
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

export default RFQ
