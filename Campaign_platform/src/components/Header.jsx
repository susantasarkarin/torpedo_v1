import { useLocation, Link } from "react-router-dom"

function Header() {
  const location = useLocation()

  const getPageTitle = () => {
    const path = location.pathname
    if (path === "/") return "Dashboard"
    if (path.includes("/sales/campaign/list/create-contacts")) return "Create New Contacts"
    if (path.includes("/sales/campaign/list")) return "Contact Lists"
    if (path.includes("/sales/campaign/templates")) return "Email Templates"
    if (path.includes("/sales/campaign/workflow")) return "Campaign Workflow"
    if (path.includes("/sales/campaign/reports")) return "Campaign Reports"
    if (path.includes("/sales/campaign")) return "Campaign Management"
    if (path.includes("/sales/leads")) return "Lead Management"
    if (path.includes("/sales/contacts")) return "Contact Management"
    if (path.includes("/sales/account")) return "Account Management"
    if (path.includes("/sales/rfq")) return "Request for Quotation"
    if (path.includes("/sales")) return "Sales Dashboard"
    if (path.includes("/marketing")) return "Marketing Dashboard"
    if (path.includes("/finance")) return "Finance Dashboard"
    if (path.includes("/operations")) return "Operations Dashboard"
    if (path.includes("/hr")) return "HR Dashboard"
    return "Dashboard"
  }

  return (
    <header className="header">
      <div className="nav-container">
        <h1 style={{ fontSize: "1.5rem", fontWeight: "600", color: "#1e293b" }}>{getPageTitle()}</h1>
        <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
          <span style={{ color: "#64748b", fontSize: "0.875rem" }}>Welcome back, Admin</span>
          <Link to="/login" className="btn btn-outline" style={{ padding: "0.5rem 1rem" }}>
            Logout
          </Link>
        </div>
      </div>
    </header>
  )
}

export default Header
