"use client"

import { Link, useLocation } from "react-router-dom"
import "./OperationsSidebar.css"

function OperationsSidebar() {
  const location = useLocation()

  const isActive = (path) => location.pathname.startsWith(path)

  return (
    <aside className="operations-sidebar">
      <div className="sidebar-section">
        <h3 className="sidebar-title">Operations</h3>
      </div>
      <nav className="sidebar-menu">
        <ul>
          <li className={`sidebar-item ${isActive("/operations/clients") ? "active" : ""}`}>
            <Link to="/admin/operations/clients" className="sidebar-link">
              <span className="sidebar-icon">👤</span> Clients
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/vendors") ? "active" : ""}`}>
            <Link to="/admin/operations/vendors" className="sidebar-link">
              <span className="sidebar-icon">🏢</span> Vendors
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/projects") ? "active" : ""}`}>
            <Link to="/admin/operations/projects" className="sidebar-link">
              <span className="sidebar-icon">📂</span> Projects
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/survey-pool") ? "active" : ""}`}>
            <Link to="/admin/operations/survey-pool" className="sidebar-link">
              <span className="sidebar-icon">📋</span> Survey Pool
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/quotas") ? "active" : ""}`}>
            <Link to="/admin/operations/quotas" className="sidebar-link">
              <span className="sidebar-icon">📊</span> Traffic Management
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/reports") ? "active" : ""}`}>
            <Link to="/admin/operations/reports" className="sidebar-link">
              <span className="sidebar-icon">📑</span> Reports
            </Link>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

export default OperationsSidebar
