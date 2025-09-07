function Account() {
  const sampleAccounts = [
    { id: 1, name: "TechCorp Inc.", contact: "John Smith", value: "$50,000", status: "Active" },
    { id: 2, name: "Business Solutions", contact: "Sarah Johnson", value: "$75,000", status: "Pending" },
    { id: 3, name: "StartupXYZ", contact: "Mike Davis", value: "$25,000", status: "Active" },
    { id: 4, name: "Enterprise Ltd.", contact: "Lisa Wilson", value: "$120,000", status: "Negotiating" },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Account Management</h2>
          <p className="card-description">Manage customer accounts and relationship data.</p>
        </div>
        <div className="mb-4">
          <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
            Add New Account
          </button>
          <button className="btn btn-secondary">Export Accounts</button>
        </div>
        <div className="card">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e5e7eb" }}>
                <th style={{ padding: "1rem", textAlign: "left" }}>Account Name</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Primary Contact</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Account Value</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Status</th>
                <th style={{ padding: "1rem", textAlign: "left" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sampleAccounts.map((account) => (
                <tr key={account.id} style={{ borderBottom: "1px solid #f3f4f6" }}>
                  <td style={{ padding: "1rem", fontWeight: "600" }}>{account.name}</td>
                  <td style={{ padding: "1rem" }}>{account.contact}</td>
                  <td style={{ padding: "1rem", fontWeight: "600", color: "#10b981" }}>{account.value}</td>
                  <td style={{ padding: "1rem" }}>
                    <span
                      style={{
                        padding: "0.25rem 0.75rem",
                        borderRadius: "9999px",
                        fontSize: "0.75rem",
                        backgroundColor: account.status === "Active" ? "#dcfce7" : "#fef3c7",
                        color: account.status === "Active" ? "#166534" : "#92400e",
                      }}
                    >
                      {account.status}
                    </span>
                  </td>
                  <td style={{ padding: "1rem" }}>
                    <button className="btn btn-outline" style={{ padding: "0.25rem 0.75rem", fontSize: "0.75rem" }}>
                      Manage
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

export default Account
