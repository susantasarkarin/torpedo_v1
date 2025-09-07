function Operations() {
  const operationsMetrics = [
    { title: "Active Projects", value: "12", change: "3 due this week" },
    { title: "Team Productivity", value: "94%", change: "+2% from last week" },
    { title: "System Uptime", value: "99.8%", change: "No incidents" },
    { title: "Pending Tasks", value: "47", change: "15 high priority" },
  ]

  const recentActivities = [
    { id: 1, activity: "Email server maintenance completed", time: "2 hours ago", status: "Completed" },
    { id: 2, activity: "New campaign template deployed", time: "4 hours ago", status: "Completed" },
    { id: 3, activity: "Database backup in progress", time: "6 hours ago", status: "In Progress" },
    { id: 4, activity: "Security audit scheduled", time: "1 day ago", status: "Scheduled" },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Operations Dashboard</h2>
          <p className="card-description">Monitor system performance, project status, and operational efficiency.</p>
        </div>

        <div className="grid grid-cols-2 mb-6">
          {operationsMetrics.map((metric, index) => (
            <div key={index} className="card">
              <h3 className="card-title">{metric.title}</h3>
              <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6", marginBottom: "0.5rem" }}>
                {metric.value}
              </p>
              <p style={{ fontSize: "0.875rem", color: "#6b7280" }}>{metric.change}</p>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">System Status</h3>
            <div style={{ marginTop: "1rem" }}>
              <div
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}
              >
                <span>Email Service</span>
                <span style={{ color: "#10b981", fontWeight: "600" }}>● Online</span>
              </div>
              <div
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}
              >
                <span>Database</span>
                <span style={{ color: "#10b981", fontWeight: "600" }}>● Online</span>
              </div>
              <div
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}
              >
                <span>API Gateway</span>
                <span style={{ color: "#10b981", fontWeight: "600" }}>● Online</span>
              </div>
              <div
                style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}
              >
                <span>Analytics</span>
                <span style={{ color: "#fbbf24", fontWeight: "600" }}>● Maintenance</span>
              </div>
            </div>
            <button className="btn btn-outline">View Details</button>
          </div>

          <div className="card">
            <h3 className="card-title">Recent Activities</h3>
            <div style={{ marginTop: "1rem" }}>
              {recentActivities.map((activity) => (
                <div
                  key={activity.id}
                  style={{
                    padding: "0.75rem 0",
                    borderBottom: "1px solid #f3f4f6",
                  }}
                >
                  <p style={{ fontWeight: "500", marginBottom: "0.25rem" }}>{activity.activity}</p>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <p style={{ fontSize: "0.75rem", color: "#6b7280" }}>{activity.time}</p>
                    <span
                      style={{
                        fontSize: "0.75rem",
                        padding: "0.125rem 0.5rem",
                        borderRadius: "9999px",
                        backgroundColor:
                          activity.status === "Completed"
                            ? "#dcfce7"
                            : activity.status === "In Progress"
                              ? "#dbeafe"
                              : "#fef3c7",
                        color:
                          activity.status === "Completed"
                            ? "#166534"
                            : activity.status === "In Progress"
                              ? "#1e40af"
                              : "#92400e",
                      }}
                    >
                      {activity.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <h3 className="card-title">Quick Actions</h3>
          <div className="grid grid-cols-3" style={{ marginTop: "1rem" }}>
            <button className="btn btn-primary">System Backup</button>
            <button className="btn btn-secondary">Performance Report</button>
            <button className="btn btn-outline">Schedule Maintenance</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Operations
