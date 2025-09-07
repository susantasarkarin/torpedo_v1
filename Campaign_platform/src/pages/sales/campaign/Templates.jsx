function Templates() {
  const sampleTemplates = [
    { id: 1, name: "Welcome Email", category: "Onboarding", usage: 45, lastUsed: "2024-01-15" },
    { id: 2, name: "Product Demo Invitation", category: "Sales", usage: 32, lastUsed: "2024-01-14" },
    { id: 3, name: "Follow-up Sequence", category: "Nurturing", usage: 28, lastUsed: "2024-01-12" },
    { id: 4, name: "Newsletter Template", category: "Marketing", usage: 67, lastUsed: "2024-01-16" },
    { id: 5, name: "Abandoned Cart", category: "E-commerce", usage: 89, lastUsed: "2024-01-16" },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Email Templates</h2>
          <p className="card-description">Create, manage, and organize your email templates for campaigns.</p>
        </div>

        <div className="mb-6">
          <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
            Create Template
          </button>
          <button className="btn btn-secondary" style={{ marginRight: "1rem" }}>
            Import Template
          </button>
          <button className="btn btn-outline">Template Library</button>
        </div>

        <div className="grid grid-cols-3 mb-6">
          <div className="card">
            <h3 className="card-title">Total Templates</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6" }}>28</p>
            <p className="card-description">Ready to use</p>
          </div>
          <div className="card">
            <h3 className="card-title">Most Used</h3>
            <p style={{ fontSize: "1.25rem", fontWeight: "bold", color: "#10b981" }}>Abandoned Cart</p>
            <p className="card-description">89 times used</p>
          </div>
          <div className="card">
            <h3 className="card-title">Categories</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#f59e0b" }}>5</p>
            <p className="card-description">Template categories</p>
          </div>
        </div>

        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h3 className="card-title">Template Library</h3>
            <select className="form-input" style={{ width: "auto" }}>
              <option>All Categories</option>
              <option>Onboarding</option>
              <option>Sales</option>
              <option>Marketing</option>
              <option>Nurturing</option>
              <option>E-commerce</option>
            </select>
          </div>

          <div className="grid grid-cols-2">
            {sampleTemplates.map((template) => (
              <div key={template.id} className="card" style={{ margin: "0.5rem" }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "start",
                    marginBottom: "1rem",
                  }}
                >
                  <div>
                    <h4 style={{ fontWeight: "600", marginBottom: "0.5rem" }}>{template.name}</h4>
                    <span
                      style={{
                        padding: "0.25rem 0.5rem",
                        borderRadius: "4px",
                        fontSize: "0.75rem",
                        backgroundColor: "#f3f4f6",
                        color: "#374151",
                      }}
                    >
                      {template.category}
                    </span>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>Used {template.usage} times</p>
                    <p style={{ fontSize: "0.75rem", color: "#9ca3af" }}>Last: {template.lastUsed}</p>
                  </div>
                </div>
                <div style={{ display: "flex", gap: "0.5rem" }}>
                  <button className="btn btn-outline" style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", flex: 1 }}>
                    Preview
                  </button>
                  <button className="btn btn-primary" style={{ padding: "0.5rem 1rem", fontSize: "0.75rem", flex: 1 }}>
                    Use Template
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

export default Templates
