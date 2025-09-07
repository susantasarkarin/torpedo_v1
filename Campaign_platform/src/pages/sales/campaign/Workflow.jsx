function Workflow() {
  const sampleWorkflows = [
    { id: 1, name: "New Lead Nurturing", status: "Active", triggers: 3, actions: 7, contacts: 245 },
    { id: 2, name: "Customer Onboarding", status: "Active", triggers: 2, actions: 5, contacts: 89 },
    { id: 3, name: "Re-engagement Campaign", status: "Paused", triggers: 1, actions: 4, contacts: 156 },
    { id: 4, name: "Product Demo Follow-up", status: "Draft", triggers: 2, actions: 3, contacts: 0 },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Campaign Workflows</h2>
          <p className="card-description">
            Create automated email sequences and workflows to nurture leads and engage customers.
          </p>
        </div>

        <div className="mb-6">
          <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
            Create Workflow
          </button>
          <button className="btn btn-secondary" style={{ marginRight: "1rem" }}>
            Workflow Templates
          </button>
          <button className="btn btn-outline">Import Workflow</button>
        </div>

        <div className="grid grid-cols-3 mb-6">
          <div className="card">
            <h3 className="card-title">Active Workflows</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#10b981" }}>2</p>
            <p className="card-description">Currently running</p>
          </div>
          <div className="card">
            <h3 className="card-title">Total Contacts</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6" }}>490</p>
            <p className="card-description">In active workflows</p>
          </div>
          <div className="card">
            <h3 className="card-title">Automation Rate</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#f59e0b" }}>87%</p>
            <p className="card-description">Of campaigns automated</p>
          </div>
        </div>

        <div className="card">
          <h3 className="card-title mb-4">Workflow Management</h3>
          <div className="grid">
            {sampleWorkflows.map((workflow) => (
              <div key={workflow.id} className="card" style={{ margin: "0.5rem 0" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                  <div style={{ flex: 1 }}>
                    <h4 style={{ fontWeight: "600", marginBottom: "0.5rem" }}>{workflow.name}</h4>
                    <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
                      <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>{workflow.triggers} Triggers</span>
                      <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>{workflow.actions} Actions</span>
                      <span style={{ fontSize: "0.875rem", color: "#6b7280" }}>{workflow.contacts} Contacts</span>
                    </div>
                    <span
                      style={{
                        padding: "0.25rem 0.75rem",
                        borderRadius: "9999px",
                        fontSize: "0.75rem",
                        backgroundColor:
                          workflow.status === "Active"
                            ? "#dcfce7"
                            : workflow.status === "Paused"
                              ? "#fef3c7"
                              : "#f3f4f6",
                        color:
                          workflow.status === "Active"
                            ? "#166534"
                            : workflow.status === "Paused"
                              ? "#92400e"
                              : "#374151",
                      }}
                    >
                      {workflow.status}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <button className="btn btn-outline" style={{ padding: "0.5rem 1rem", fontSize: "0.75rem" }}>
                      Edit
                    </button>
                    <button className="btn btn-secondary" style={{ padding: "0.5rem 1rem", fontSize: "0.75rem" }}>
                      View
                    </button>
                    {workflow.status === "Active" ? (
                      <button
                        className="btn"
                        style={{
                          padding: "0.5rem 1rem",
                          fontSize: "0.75rem",
                          backgroundColor: "#fbbf24",
                          color: "white",
                        }}
                      >
                        Pause
                      </button>
                    ) : (
                      <button className="btn btn-primary" style={{ padding: "0.5rem 1rem", fontSize: "0.75rem" }}>
                        Start
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h3 className="card-title mb-4">Workflow Builder</h3>
          <div
            style={{
              border: "2px dashed #d1d5db",
              borderRadius: "8px",
              padding: "3rem",
              textAlign: "center",
              backgroundColor: "#f9fafb",
            }}
          >
            <h4 style={{ marginBottom: "1rem", color: "#6b7280" }}>Drag & Drop Workflow Builder</h4>
            <p style={{ marginBottom: "2rem", color: "#9ca3af" }}>
              Create complex automated workflows with our visual builder
            </p>
            <button className="btn btn-primary">Open Workflow Builder</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Workflow
