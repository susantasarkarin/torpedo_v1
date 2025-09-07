function Dashboard() {
  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Welcome to Email Campaigns Platform</h2>
          <p className="card-description">
            Manage your automated email campaigns, leads, and customer relationships all in one place.
          </p>
        </div>
        <div className="grid grid-cols-3">
          <div className="card">
            <h3 className="card-title">Active Campaigns</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6" }}>12</p>
            <p className="card-description">Currently running</p>
          </div>
          <div className="card">
            <h3 className="card-title">Total Leads</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#10b981" }}>1,247</p>
            <p className="card-description">In your database</p>
          </div>
          <div className="card">
            <h3 className="card-title">Email Templates</h3>
            <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#f59e0b" }}>28</p>
            <p className="card-description">Ready to use</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Dashboard
