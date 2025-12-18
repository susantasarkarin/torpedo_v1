function HR() {
  const hrMetrics = [
    { title: "Total Employees", value: "24", change: "2 new hires this month" },
    { title: "Open Positions", value: "3", change: "1 urgent" },
    { title: "Employee Satisfaction", value: "4.2/5", change: "+0.3 from last survey" },
    { title: "Pending Reviews", value: "8", change: "Due this week" },
  ]

  const recentHRActivities = [
    { id: 1, activity: "New employee onboarding - Sarah Johnson", time: "1 day ago", type: "Onboarding" },
    { id: 2, activity: "Performance review completed - Mike Davis", time: "2 days ago", type: "Review" },
    { id: 3, activity: "Job posting published - Senior Developer", time: "3 days ago", type: "Recruitment" },
    { id: 4, activity: "Training session scheduled - Team Building", time: "1 week ago", type: "Training" },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">HR Dashboard</h2>
          <p className="card-description">
            Manage human resources, employee data, recruitment, and organizational development.
          </p>
        </div>

        <div className="grid grid-cols-2 mb-6">
          {hrMetrics.map((metric, index) => (
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
            <h3 className="card-title">Employee Management</h3>
            <div className="grid" style={{ gap: "1rem", marginTop: "1rem" }}>
              <button className="btn btn-primary">Add Employee</button>
              <button className="btn btn-secondary">Employee Directory</button>
              <button className="btn btn-outline">Performance Reviews</button>
              <button className="btn btn-outline">Time & Attendance</button>
            </div>
          </div>

          <div className="card">
            <h3 className="card-title">Recruitment</h3>
            <div className="grid" style={{ gap: "1rem", marginTop: "1rem" }}>
              <button className="btn btn-primary">Post Job</button>
              <button className="btn btn-secondary">View Applications</button>
              <button className="btn btn-outline">Interview Schedule</button>
              <button className="btn btn-outline">Candidate Pipeline</button>
            </div>
          </div>
        </div>

        <div className="card">
          <h3 className="card-title">Recent HR Activities</h3>
          <div style={{ marginTop: "1rem" }}>
            {recentHRActivities.map((activity) => (
              <div
                key={activity.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "0.75rem 0",
                  borderBottom: "1px solid #f3f4f6",
                }}
              >
                <div>
                  <p style={{ fontWeight: "500", marginBottom: "0.25rem" }}>{activity.activity}</p>
                  <p style={{ fontSize: "0.75rem", color: "#6b7280" }}>{activity.time}</p>
                </div>
                <span
                  style={{
                    fontSize: "0.75rem",
                    padding: "0.25rem 0.75rem",
                    borderRadius: "9999px",
                    backgroundColor: "#f3f4f6",
                    color: "#374151",
                  }}
                >
                  {activity.type}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <h3 className="card-title">Training & Development</h3>
          <div className="grid grid-cols-3" style={{ marginTop: "1rem" }}>
            <button className="btn btn-primary">Schedule Training</button>
            <button className="btn btn-secondary">Learning Resources</button>
            <button className="btn btn-outline">Skill Assessment</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default HR
