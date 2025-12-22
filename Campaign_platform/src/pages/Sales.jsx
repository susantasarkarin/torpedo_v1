import { Link } from "react-router-dom"

function Sales() {
  return (
    <div>
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Sales Dashboard</h2>
          <p className="card-description">Manage your sales campaigns, leads, contacts, and customer accounts.</p>
        </div>
        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title">Campaign Management</h3>
            <p className="card-description mb-4">Create and manage email campaigns, templates, and workflows.</p>
            <Link to="/sales/campaign" className="btn btn-primary">
              Manage Campaigns
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">Lead Management</h3>
            <p className="card-description mb-4">Track and nurture your sales leads through the pipeline.</p>
            <Link to="/sales/leads" className="btn btn-primary">
              View Leads
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">Contact Management</h3>
            <p className="card-description mb-4">Upload and manage your email contact lists and segments.</p>
            <Link to="/sales/contacts" className="btn btn-primary">
              Manage Contacts
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title">Account Management</h3>
            <p className="card-description mb-4">Manage customer accounts and relationship data.</p>
            <Link to="/sales/account" className="btn btn-primary">
              View Accounts
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Sales
