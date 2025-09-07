function Contacts() {
  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Contact Management</h2>
          <p className="card-description">Upload and manage your email contact lists and segments.</p>
        </div>
        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">Upload Contacts</h3>
            <p className="card-description mb-4">Import contacts from CSV files or add them manually.</p>
            <div className="mb-4">
              <input type="file" accept=".csv" className="form-input mb-4" style={{ padding: "0.5rem" }} />
            </div>
            <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
              Upload Contacts
            </button>
            <button className="btn btn-outline">Add Manually</button>
          </div>
          <div className="card">
            <h3 className="card-title">Contact Lists</h3>
            <p className="card-description mb-4">Manage and segment your contact lists.</p>
            <div style={{ marginBottom: "1rem" }}>
              <div
                style={{
                  padding: "1rem",
                  border: "1px solid #e5e7eb",
                  borderRadius: "6px",
                  marginBottom: "0.5rem",
                }}
              >
                <h4 style={{ fontWeight: "600", marginBottom: "0.5rem" }}>Main List</h4>
                <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>1,247 contacts</p>
              </div>
              <div
                style={{
                  padding: "1rem",
                  border: "1px solid #e5e7eb",
                  borderRadius: "6px",
                  marginBottom: "0.5rem",
                }}
              >
                <h4 style={{ fontWeight: "600", marginBottom: "0.5rem" }}>VIP Customers</h4>
                <p style={{ color: "#6b7280", fontSize: "0.875rem" }}>89 contacts</p>
              </div>
            </div>
            <button className="btn btn-secondary">Create New List</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Contacts
