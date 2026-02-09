"use client"

import { useState } from "react"
import { Link, useLocation } from "react-router-dom"
import "./OperationsSidebar.css"

function OperationsSidebar() {
  const location = useLocation()
  const [trafficOpen, setTrafficOpen] = useState(true)

  const isActive = (path) => location.pathname.startsWith(path)

  return (
    <aside className="operations-sidebar">
      <div className="sidebar-section">
        <h3 className="sidebar-title">Operations</h3>
      </div>
      <nav className="sidebar-menu">
        <ul>
          <li className={`sidebar-item ${isActive("/admin/operations/clients") ? "active" : ""}`}>
            <Link to="/admin/operations/clients" className="sidebar-link">
              <span className="sidebar-icon">👤</span> Clients
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/operations/vendors") ? "active" : ""}`}>
            <Link to="/admin/operations/vendors" className="sidebar-link">
              <span className="sidebar-icon">🏢</span> Vendors
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/operations/projects") ? "active" : ""}`}>
            <Link to="/admin/operations/projects" className="sidebar-link">
              <span className="sidebar-icon">📂</span> Projects
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/operations/survey-pool") ? "active" : ""}`}>
            <Link to="/admin/operations/survey-pool" className="sidebar-link">
              <span className="sidebar-icon">📋</span> Survey Pool
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/operations/potential-clients") ? "active" : ""}`}>
            <Link to="/admin/operations/potential-clients" className="sidebar-link">
              <span className="sidebar-icon">💼</span> Potential Client
            </Link>
          </li>
          <li className={`sidebar-item ${isActive("/admin/operations/rate-card") ? "active" : ""}`}>
            <Link to="/admin/operations/rate-card" className="sidebar-link">
              <span className="sidebar-icon">💵</span> Rate Card
            </Link>
          </li>

          {/* Traffic Group */}
          <li className="sidebar-group">
            <div 
              className="sidebar-group-header" 
              onClick={() => setTrafficOpen(!trafficOpen)}
              role="button"
            >
              <span className="sidebar-icon">🚦</span>
              <span className="sidebar-group-title">Traffic</span>
              <span className={`sidebar-chevron ${trafficOpen ? 'open' : ''}`}>▾</span>
            </div>
            <ul className={`sidebar-submenu ${trafficOpen ? 'open' : ''}`}>
              <li className={`sidebar-subitem ${isActive("/admin/operations/traffic") ? "active" : ""}`}>
                <Link to="/admin/operations/traffic" className="sidebar-sublink">
                  <span className="sidebar-icon">📥</span> Inbound Traffic
                </Link>
              </li>
              <li className={`sidebar-subitem ${isActive("/admin/operations/reports") ? "active" : ""}`}>
                <Link to="/admin/operations/reports" className="sidebar-sublink">
                  <span className="sidebar-icon">📤</span> Outbound Traffic
                </Link>
              </li>
            </ul>
          </li>
        </ul>
      </nav>
    </aside>
  )
}

export default OperationsSidebar
