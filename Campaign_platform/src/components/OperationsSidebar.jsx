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
            <Link to="/operations/clients" className="sidebar-link">
              <span className="sidebar-icon">👤</span> Clients
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/vendors") ? "active" : ""}`}>
            <Link to="/operations/vendors" className="sidebar-link">
              <span className="sidebar-icon">🏢</span> Vendors
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/projects") ? "active" : ""}`}>
            <Link to="/operations/projects" className="sidebar-link">
              <span className="sidebar-icon">📂</span> Projects
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/quotas") ? "active" : ""}`}>
            <Link to="/operations/quotas" className="sidebar-link">
              <span className="sidebar-icon">📊</span> Quota Monitoring
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/operations/reports") ? "active" : ""}`}>
            <Link to="/operations/reports" className="sidebar-link">
              <span className="sidebar-icon">📑</span> Reports
            </Link>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

export default OperationsSidebar
