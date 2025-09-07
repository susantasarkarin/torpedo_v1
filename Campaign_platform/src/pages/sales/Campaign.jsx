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
            <Link to="/sales/campaign/list" className="btn btn-primary">
              Manage Lists
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">Email Templates</h3>
            <p className="card-description mb-4">Design and manage reusable email templates for your campaigns.</p>
            <Link to="/sales/campaign/templates" className="btn btn-primary">
              Manage Templates
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">Campaign Workflows</h3>
            <p className="card-description mb-4">Set up automated workflows and email sequences.</p>
            <Link to="/sales/campaign/workflow" className="btn btn-primary">
              Manage Workflows
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">Campaign Reports</h3>
            <p className="card-description mb-4">View detailed analytics and performance reports.</p>
            <Link to="/sales/campaign/reports" className="btn btn-primary">
              View Reports
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Campaign
