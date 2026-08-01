import { Link } from "react-router-dom"

function Campaign() {
  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Campaign Management</h2>
          <p className="card-description">Create, manage, and monitor your email marketing campaigns.</p>
        </div>
        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">Contact Lists</h3>
            <p className="card-description mb-4">Create and manage contact lists for your campaigns.</p>
            <Link to="/admin/sales/campaign/list" className="btn btn-primary">
              Manage Lists
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">AI Leads</h3>
            <p className="card-description mb-4">Discover, enrich, and qualify leads for your campaigns.</p>
            <Link to="/admin/sales/campaign/ai-leads" className="btn btn-primary">
              Manage Leads
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">Campaign Workflows</h3>
            <p className="card-description mb-4">Set up automated workflows and email sequences.</p>
            <Link to="/admin/sales/campaign/workflow" className="btn btn-primary">
              Manage Workflows
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">Email Patterns</h3>
            <p className="card-description mb-4">Analyse and build verified email address patterns by domain.</p>
            <Link to="/admin/sales/campaign/email-patterns" className="btn btn-primary">
              View Patterns
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Campaign
