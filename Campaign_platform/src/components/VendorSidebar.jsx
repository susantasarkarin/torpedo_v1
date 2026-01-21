"use client"

import { Link, useLocation } from "react-router-dom"
import "./VendorSidebar.css"

function VendorSidebar() {
  const location = useLocation()

  const isActive = (path) => location.pathname.startsWith(path)

  return (
    <aside className="vendor-sidebar">
      <div className="sidebar-header">
        <h2>🏢 Vendors</h2>
      </div>
      <nav className="sidebar-menu">
        <ul>
          <li className={`sidebar-item ${location.pathname === "/admin/vendor" ? "active" : ""}`}>
            <Link to="/admin/vendor" className="sidebar-link">
              <span className="sidebar-icon">📊</span> Dashboard
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/vendor/leads") ? "active" : ""}`}>
            <Link to="/admin/vendor/leads" className="sidebar-link">
              <span className="sidebar-icon">👥</span> Vendor Leads
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/vendor/all") ? "active" : ""}`}>
            <Link to="/admin/vendor/all" className="sidebar-link">
              <span className="sidebar-icon">🏢</span> Vendors
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/vendor/billing") ? "active" : ""}`}>
            <Link to="/admin/vendor/billing" className="sidebar-link">
              <span className="sidebar-icon">💰</span> Billing
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/vendor/payments") ? "active" : ""}`}>
            <Link to="/admin/vendor/payments" className="sidebar-link">
              <span className="sidebar-icon">💳</span> Payment
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/vendor/reports") ? "active" : ""}`}>
            <Link to="/admin/vendor/reports" className="sidebar-link">
              <span className="sidebar-icon">📈</span> Reports
            </Link>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

export default VendorSidebar
