import { Link } from "react-router-dom"
import { BarChart3, Target, Users, Building2, Mail, FileText } from "lucide-react"

function Sales() {
  return (
    <div>
      {/* Main Dashboard Card - Prominent */}
      <div className="card" style={{ marginBottom: "1.5rem", background: "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)", border: "1px solid #334155" }}>
        <div className="card-header">
          <h2 className="card-title" style={{ color: "#f8fafc", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <BarChart3 size={24} />
            Sales Dashboard
          </h2>
          <p className="card-description" style={{ color: "#94a3b8" }}>
            Conversion-focused KPIs: funnel analysis, velocity metrics, revenue reality
          </p>
        </div>
        <div style={{ padding: "1rem 1.5rem" }}>
          <Link to="/admin/sales/dashboard" className="btn btn-primary" style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.5rem",
            padding: "0.75rem 1.5rem",
            backgroundColor: "#3b82f6",
            color: "white",
            textDecoration: "none",
            borderRadius: "0.5rem",
            fontWeight: "600"
          }}>
            <Target size={18} />
            Open Sales Dashboard
          </Link>
        </div>
      </div>

      {/* Management Cards */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Sales Management</h2>
          <p className="card-description">Manage your sales campaigns, leads, contacts, and customer accounts.</p>
        </div>
        <div className="grid grid-cols-2">
          <div className="card">
            <h3 className="card-title" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <Mail size={18} />
              Campaign Management
            </h3>
            <p className="card-description mb-4">Create and manage email campaigns, templates, and workflows.</p>
            <Link to="/admin/sales/campaign" className="btn btn-primary">
              Manage Campaigns
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <Target size={18} />
              Lead Management
            </h3>
            <p className="card-description mb-4">Track and nurture your sales leads through the pipeline.</p>
            <Link to="/admin/sales/leads" className="btn btn-primary">
              View Leads
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <Users size={18} />
              Contact Management
            </h3>
            <p className="card-description mb-4">Upload and manage your email contact lists and segments.</p>
            <Link to="/admin/sales/contacts" className="btn btn-primary">
              Manage Contacts
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <Building2 size={18} />
              Account Management
            </h3>
            <p className="card-description mb-4">Manage customer accounts and relationship data.</p>
            <Link to="/admin/sales/account" className="btn btn-primary">
              View Accounts
            </Link>
          </div>
          <div className="card">
            <h3 className="card-title" style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <FileText size={18} />
              RFQ Management
            </h3>
            <p className="card-description mb-4">Manage requests for quotations and deal tracking.</p>
            <Link to="/admin/sales/rfq" className="btn btn-primary">
              View RFQs
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

export default Sales
