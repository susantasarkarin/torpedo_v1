function Marketing() {
  const marketingMetrics = [
    { title: "Active Campaigns", value: "8", change: "+2 this month" },
    { title: "Total Reach", value: "45,230", change: "+12% from last month" },
    { title: "Engagement Rate", value: "6.8%", change: "+0.5% improvement" },
    { title: "Lead Generation", value: "234", change: "+18% this month" },
  ]

  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Marketing Dashboard</h2>
          <p className="card-description">
            Manage your marketing campaigns, content strategy, and brand communications.
          </p>
        </div>

        <div className="grid grid-cols-2 mb-6">
          {marketingMetrics.map((metric, index) => (
            <div key={index} className="card">
              <h3 className="card-title">{metric.title}</h3>
              <p style={{ fontSize: "2rem", fontWeight: "bold", color: "#3b82f6", marginBottom: "0.5rem" }}>
                {metric.value}
              </p>
              <p style={{ fontSize: "0.875rem", color: "#10b981" }}>{metric.change}</p>
            </div>
          ))}
        </div>

        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">Content Marketing</h3>
            <p className="card-description mb-4">Create and manage your content marketing strategy.</p>
            <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
              Create Content
            </button>
            <button className="btn btn-outline">Content Calendar</button>
          </div>

          <div className="card">
            <h3 className="card-title">Social Media</h3>
            <p className="card-description mb-4">Manage your social media presence and campaigns.</p>
            <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
              Schedule Posts
            </button>
            <button className="btn btn-outline">Analytics</button>
          </div>

          <div className="card">
            <h3 className="card-title">Brand Management</h3>
            <p className="card-description mb-4">Maintain brand consistency across all channels.</p>
            <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
              Brand Assets
            </button>
            <button className="btn btn-outline">Guidelines</button>
          </div>

          <div className="card">
            <h3 className="card-title">Market Research</h3>
            <p className="card-description mb-4">Analyze market trends and competitor insights.</p>
            <button className="btn btn-primary" style={{ marginRight: "1rem" }}>
              View Research
            </button>
            <button className="btn btn-outline">Competitor Analysis</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Marketing
